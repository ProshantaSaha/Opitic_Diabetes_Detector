#!/usr/bin/python -W ignore
########################################################## {COPYRIGHT-TOP} ###
# Licensed Materials - Property of IBM
# 5737-I32
#
# (C) Copyright IBM Corp. 2018
#
# US Government Users Restricted Rights - Use, duplication, or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
########################################################## {COPYRIGHT-END} ###

import random
from agent_lib import ActionAgentBase


class SampleActionAgent(ActionAgentBase):
    """ Sample agent to test registration and communication with Spectrum Discover.

    This script expect configuration parameters to be specified as environment
    variables.

    SPECTRUM_DISCOVER_HOST .... Spectrum Discover server (domain, IP address)
                                - default: https://localhost

    AGENT_NAME ................ The name of the agent to be registered
                                - default: sd_sample_agent

    AGENT_USER ................ The user who is used to obtain authentication token
    AGENT_USER_PASSWORD

    KAFKA_DIR ................. The directory where TLS certificates will be saved
                                - absolute or relative path
                                - default: kafka (relative path to this script)

    LOG_LEVEL ................. Log verbosity level (ERROR, WARNING, INFO, DEBUG)
                                - default: DEBUG
    """

    def on_agent_message(self, msg):
        """ Process messages from Spectrum Discover.
        Input messages are from Kafka consumer and returned messages are sent to producer.
        This is the main method for implementing agent and processing messages.
        If this method raise an error it will be handled in the base class, logged and
        processing will continue.
        """

        batch = self.build_completion_hdr(msg)

        for doc in msg['docs']:
            rando = random.randint(0, 99)
            if rando % 2 == 0:
                doc['tags'] = {'classification': 'public'}
            elif rando % 3 == 0:
                doc['tags'] = {'classification': 'confidential'}
            elif rando % 5 == 0:
                doc['tags'] = {'classification': 'pii'}
            else:
                doc['tags'] = {'classification': 'sensitive'}
            doc['status'] = 'success'

            agent.logger.debug("Adding doc with id %s to completion message", doc['fkey'])
            self.add_doc_to_completion_batch(doc, batch)

        # Return message will be sent to Kafka producer
        return batch

    def build_completion_hdr(self, doc):
        batch = {
            'mo_ver': doc['mo_ver'],
            'action_id': doc['action_id'],
            'policy_id': doc['policy_id'],
        }

        self.logger.debug("Assembled batch header: %s", batch)

        return batch

    def add_doc_to_completion_batch(self, doc, batch):
        if 'docs' in batch:
            batch['docs'] += [doc]
        else:
            batch['docs'] = [doc]


'''
#####################################################################
#                                                                   #
#                      IBM Spectrum Discover                        #
#                  Sample Agent - main function                     #
#                                                                   #
#####################################################################
'''
if __name__ == "__main__":
    # The first time agent is started it will be registered
    # with these options.
    registration_info = {
        # "action_agent": "<AGENT_NAME>" is set in the base class
        "action_id": "DEEPINSPECT",
        "action_params": ["extract_tags"]
    }

    # Create sample agent instance
    agent = SampleActionAgent(registration_info)

    # Start agent:
    # - register agent to Spectrum Discover
    # - get Kafka certificates from Spectrum Discover
    # - instantiate Kafka producer and consumer
    # - start processing Kafka messages (on_agent_message)
    agent.start()
