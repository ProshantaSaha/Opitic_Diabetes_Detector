##########################################################
# Example of library to assist in deploying Discover agents written in python
##########################################################

import os
import sys
import json
import logging
from io import open
from re import match
from functools import partial
from urlparse import urljoin
import requests
from confluent_kafka import Consumer, Producer, KafkaException, KafkaError


class ActionAgentBase(object):
    """ Sample agent to test registration and communication with Spectrum Discover.

    This script expect configuration parameters to be specified as environment
    variables.

    SPECTRUM_DISCOVER_HOST ..... Spectrum Discover server (domain, IP address)
                                 - default: https://localhost

    AGENT_NAME ................. The name of the agent to be registered
                                 - default: sd_sample_agent

    AGENT_USER ................. The user who is used to obtain authentication token
    AGENT_USER_PASSWORD

    KAFKA_DIR .................. The directory where TLS certificates will be saved
                                 - absolute or relative path
                                 - default: kafka (relative path to this script)

    LOG_LEVEL .................. Log verbosity level (ERROR, WARNING, INFO, DEBUG)
                                 - default: DEBUG
    """

    def __init__(self, reg_info):
        self.reg_info = reg_info.copy()

        # Instantiate logger
        loglevels = {'INFO': logging.INFO, 'DEBUG': logging.DEBUG,
                     'ERROR': logging.ERROR, 'WARNING': logging.WARNING}
        log_level = os.environ.get('LOG_LEVEL', 'DEBUG')
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        logging.basicConfig(stream=sys.stdout,
                            format=log_format,
                            level=loglevels[log_level])
        self.logger = logging.getLogger(__name__)

        env = lambda envKey, default: os.environ.get(envKey, default)

        # Spectrum discover host agent talks to
        self.sd_api = env('SPECTRUM_DISCOVER_HOST', 'https://localhost')

        # This agent name
        self.agent_name = env('AGENT_NAME', 'sd_sample_agent')

        # The user account assigned to this agent
        self.agent_user          = env('AGENT_USER', '')
        self.agent_user_password = env('AGENT_USER_PASSWORD', '')
        self.agent_token         = None

        # Endpoints used by agent
        sd_endpoint = partial(urljoin, self.sd_api)
        self.identity_auth_url = sd_endpoint('auth/v1/token')
        self.registration_url  = sd_endpoint('policyengine/v1/agents')
        self.certificates_url  = sd_endpoint('policyengine/v1/tlscert')

        # Certificates directory and file paths
        cert_dir = env('KAFKA_DIR', 'kafka')
        if not os.path.isabs(cert_dir):
            cert_dir = os.path.join(os.getcwd(), cert_dir)

        self.certificates_dir = os.path.normpath(cert_dir)
        cert_path = partial(os.path.join, self.certificates_dir)
        self.kafka_client_cert = cert_path("kafka_client.crt")
        self.kafka_client_key  = cert_path("kafka_client.key")
        self.kafka_root_cert   = cert_path("kafka-ca.crt")

        # Kafka config - this info comes from registration endpoint
        self.work_q_name  = '%s_work' % self.agent_name
        self.compl_q_name = '%s_compl' % self.agent_name

        # Agent running status
        self.agent_enabled = False

        # Function that handles messages from Spectrum Discover
        self.message_handler = None

        self.logger.info("Initialize to host: %s" % self.sd_api)
        self.logger.info("Agent name: %s" % self.agent_name)
        self.logger.info("Agent user: %s" % self.agent_user)
        self.logger.info("Certificates directory: %s" % self.certificates_dir)

        if not self.agent_user:
            raise Exception("Authentication requires AGENT_USER and AGENT_USER_PASSWORD")

    def register_agent(self):
        """ Attempt to self-register an agent and receive an agent registration
        response. If the agent is already registered a 409 will be returned,
        which means another instance of this agent is already registered. In
        that case the agent should attempt a GET request to registration endpoint.
        """

        # Get authentication token if not present
        if not self.agent_token: self.obtain_token()

        # Registration request info (insert agent name)
        self.reg_info.update({
            "action_agent": self.agent_name
        })

        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' % self.agent_token
        }

        def raise_except_http(validCodes, http_code):
            if http_code not in validCodes:
                raise Exception("agent:%s, error:%d" % (self.agent_name, http_code))

        def post_register():
            response = requests.post(url=self.registration_url, verify=False, json=self.reg_info, headers=headers)

            raise_except_http([200, 201, 409], response.status_code)

            if response.status_code == 409:
                self.logger.warn('Agent already registered, initiating GET request (agent:%s)' % self.agent_name)
                return get_register()

            return response.json()

        def get_register():
            agent_url = self.registration_url + '/' + self.agent_name
            #response = requests.get(url=self.registration_url, verify=False, headers=headers)
            response = requests.get(url=agent_url, verify=False, headers=headers)

            raise_except_http([200], response.status_code)

            # GET response returns list of registrations
            reg_list = response.json()

            if not reg_list:
                raise Exception('Agent GET registration empty - (agent:%s)' % self.agent_name)

            #return reg_list[0]
            return reg_list

        try:
            resp_json = post_register()

            self.update_registration_info(resp_json)
        except Exception as e:
            self.logger.error(Exception('Agent POST registration request FAIL - (%s)' % str(e)))
            raise

    def update_registration_info(self, reg_response):
        # Record topic names and broker IP/port
        self.kafka_ip     = reg_response['broker_ip']
        self.kafka_port   = reg_response['broker_port']
        self.work_q_name  = reg_response['work_q']
        self.compl_q_name = reg_response['completion_q']
        self.kafka_host   = "%s:%s" % (self.kafka_ip, self.kafka_port)

        self.logger.info("Agent is registered")
        self.logger.info("Kafka host: %s" % self.kafka_host)
        self.logger.info("Agent attached to work queue: %s" % self.work_q_name)
        self.logger.info("Agent attached to compl queue: %s" % self.compl_q_name)

    def get_kafka_certificates(self):
        """ Download the client certificate, client key, and CA root certificate
        via REST API, parse response and save certificates to files.
        """

        self.logger.info("Download certificates and save to files")

        response = self.download_certificates()

        cert_pattern = "-----BEGIN CERTIFICATE-----[^-]+-----END CERTIFICATE-----"
        key_pattern = "-----BEGIN PRIVATE KEY-----[^-]+-----END PRIVATE KEY-----"
        certs_regex = "(%s)[\n\r]*([^-]+%s)[\n\r]*(%s)" % (cert_pattern, key_pattern, cert_pattern)

        certs = match(certs_regex, response)

        if not certs: raise Exception("Cannot parse certificates from response: %s" % response)

        client_cert, client_key, ca_root_cert = certs.groups()

        # Create certificates directory if not exist
        if not os.path.exists(self.certificates_dir):
            os.makedirs(self.certificates_dir)
        elif not os.path.isdir(self.certificates_dir):
            raise Exception("Certificates path is not a directory (%s)" % self.certificates_dir)

        def save_file(file_path, content):
            self.logger.info("Save file: %s" % file_path)

            with open(file_path, 'w') as f:
                f.write(content.decode('ascii'))

        save_file(self.kafka_client_cert, client_cert)
        save_file(self.kafka_client_key, client_key)
        save_file(self.kafka_root_cert, ca_root_cert)

    def download_certificates(self):
        """ Download the client certificate, client key, and CA root certificate via REST API to
        be imported into the agent's trust store.
        """

        self.logger.info("Loading certificates from server: %s" % self.certificates_url)

        # Get authentication token if not present
        if not self.agent_token: self.obtain_token()

        try:
            # Request TLS certificate files for kafka traffic
            headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer %s' % self.agent_token
            }
            response = requests.get(url=self.certificates_url, verify=False, headers=headers)
            self.logger.debug("CA server response (%s)" % response)

            # Return certificates data
            if response.ok: return response.content

        except requests.exceptions.HTTPError as e:
            err = "Http Error :: %s " % e
        except requests.exceptions.ConnectionError as e:
            err = "Error Connecting :: %s " % e
        except requests.exceptions.Timeout as e:
            err = "Timeout Error :: %s " % e
        except requests.exceptions.RequestException as e:
            err = "Request Error :: %s " % e
        except Exception as e:
            err = "Request Error :: %s " % str(e)

        raise Exception(err)

    def configure_kafka(self):
        # Instantiate producer
        p_conf = {
            'bootstrap.servers': '%s' % self.kafka_host,
            'ssl.certificate.location': self.kafka_client_cert,
            'ssl.key.location': self.kafka_client_key,
            'security.protocol': 'ssl', 'ssl.ca.location': self.kafka_root_cert }

        self.kafka_producer = Producer(p_conf)

        # Instantiate consumer
        c_conf = {
            'bootstrap.servers': '%s' % self.kafka_host,
            'group.id': 'myagent_grp', 'session.timeout.ms': 6000,
            'default.topic.config': { 'auto.offset.reset': 'smallest' },
            'ssl.certificate.location': self.kafka_client_cert,
            'ssl.key.location': self.kafka_client_key,
            'security.protocol': 'ssl', 'ssl.ca.location': self.kafka_root_cert }

        self.kafka_consumer = Consumer(c_conf)

    def obtain_token(self):
        """ Any action agent SDK requests to policy engine require role based
        token authentication. The user role assigned to this agent must have an
        authenticated account on the server created externally by an
        admin.
        """

        self.logger.info('Agent obtaining token from URL: %s' % self.identity_auth_url)

        try:
            basicAuth = requests.auth.HTTPBasicAuth(self.agent_user, self.agent_user_password)
            response = requests.get(url=self.identity_auth_url, verify=False, auth=basicAuth)
            # check response from identity auth server
            if response.status_code == 200:
                self.agent_token = response.headers['X-Auth-Token']
                self.logger.info('Agent token retrieved: %s...' % self.agent_token[:10])
                return self.agent_token

            raise Exception("Attempt to obtain token returned (%d)" % response.status_code)
        except Exception as e:
            self.logger.error('Agent failed to obtain token (%s)' % str(e))
            raise
        return

    def start_kafka_listener(self):
        self.logger.info("Looking for new work on the %s topic ..." % self.work_q_name)

        self.kafka_consumer.subscribe([self.work_q_name])

        while True:
            # Poll message from Kafka
            json_request_msg = self.kafka_consumer.poll(timeout=10.0)

            request_msg = self.decode_msg(json_request_msg)

            if request_msg:
                #self.logger.debug("Job Request Message: %s", request_msg)

                try:
                    # Process the message with the implementation provided by the client
                    response_msg = self.on_agent_message(request_msg)
                except Exception as e:
                    self.logger.debug("Error in Kafka message: %s" % str(request_msg))
                    self.logger.error("Error processing Kafka message: %s" % str(e))
                    continue

                self.logger.debug("on_agent_message() response_msg: %s",
                    response_msg)
                if response_msg:
                    self.logger.debug(
                        "Submitting completion status batch to topic %s", self.compl_q_name)

                    try:
                        json_response_msg = json.dumps(response_msg)
                        self.logger.debug( "JSON sent to producer: %s",
                            json_response_msg)
                        self.kafka_producer.produce(self.compl_q_name, json_response_msg)
                        self.logger.debug( "flusing producer.")
                        self.kafka_producer.flush()
                    except Exception:
                        self.logger.error("Could not produce message to topic '%s'" % self.compl_q_name)
                        self.logger.error("--| Job Response Message: %s" % json_response_msg)
                self.logger.debug( "Request msg processing complete.")

            if not self.agent_enabled:
                break

        self.logger.debug("Exit start_kafka_listener()")

    def decode_msg(self, msg):
        # Decode JSON message and log errors
        if msg:
            if not msg.error():
                return json.loads(msg.value().decode('utf-8'))

            elif msg.error().code() != KafkaError._PARTITION_EOF:
                self.logger.error(msg.error().code())

    def on_agent_message(self, message):
        """ Implement this method is all that is needed to implement custom agent.
        This methid will be called when Kafka consumer receives a message.
        If value is returned from this method it will be delivered to Kafka producer.
        """

        if self.message_handler:
            return self.message_handler(self, message)

        self.logger.warn("Please implement `on_agent_message` method or supply"
            " function to the `subscribe` method to process agent messages.")

    def subscribe(self, message_handler):
        """ Subscribe to Spectrum Discover messages. Supplied function is called
        when Kafka consumer receives a message. If value is returned from this function
        it will be delivered to Kafka producer.
        """

        if message_handler:
            self.message_handler = message_handler

    def start(self):
        self.logger.info("Starting Spectrum Discover agent...")

        # Set agent running status
        self.agent_enabled = True

        # Register this agent to Spectrum Discover
        self.register_agent()

        # Get Kafka certificates from Spectrum Discover
        self.get_kafka_certificates()

        # Instantiate Kafka producer and consumer
        self.configure_kafka()

        # Wait Kafka messages and send response
        self.start_kafka_listener()

        # Auth token will expire, remove existing so that later requests will get the new one
        self.agent_token = None

    def stop(self):
        self.logger.info("Stopping Spectrum Discover agent...")

        # Disable agent
        self.agent_enabled = False
