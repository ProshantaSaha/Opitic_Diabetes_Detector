#!/usr/bin/python -W ignore
##############################################################################
# Example of Spectrum Discover action agent for extracting user-defined
# Spectrum Scale attributes of a file.  
# Version 2.2 - 4jul2019
##############################################################################

from agent_lib import ActionAgentBase

import subprocess
import commands

class ScaleActionAgent(ActionAgentBase):
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
      Input messages are from Kafka consumer and returned messages are sent
      to producer.
      This is the main method for implementing agent and processing messages.
      If this method raise an error it should be handled in the base class,
      logged and processing will continue.
      """

      self.logger.info("Scale action agent processing input messages.")

      batch = self.build_completion_hdr(msg)

      extract_tags = msg['action_params']['extract_tags']
      self.logger.debug("extract_args=" + str(extract_tags))

      for doc in msg['docs']:

        doc['tags'] = {}
        thisPath = doc['path']
        self.logger.debug('Doc: %s' % doc['path'])

        self.logger.debug("for tag in extract_args loop.")
        for tag in extract_tags :
          # Get value of user-defined attribute
          scaleUdefAttribute = str(tag)  # FIXME?
          self.logger.debug("Calling getscaleudef(" + scaleUdefAttribute + ", " + thisPath)
          val = self.getscaleudef(scaleUdefAttribute, thisPath, "None")
          self.logger.debug("assigning, " + str(tag) + " = " + str(val))
          doc['tags'][tag] = val

        # End for loop: tag in extract_tags
        doc['status'] = 'success'
        self.logger.debug("Adding doc to completion message")

        self.logger.debug("Tag for <" + thisPath + "> = "
                + str(doc['tags']))

        self.logger.debug("Adding doc with id %s to completion message",
                str(doc['fkey']))
        self.add_doc_to_completion_batch(doc, batch)

      # End for doc loop

      # Return message will be sent to Kafka producer
      agent.logger.info("Scale action agent completed processing input.")

      return batch


    ####################################################################
    # getscaleudef() retrieves value of user-defined Scale file attribute
    # (udefattr) from the file of interest (myPath).
    # parms:
    #   self- pythonism
    #   udefattr - name of the user-defined attribute.  For brevity, this
    #     attribute does not have Scale's obligatory prefix "user."  That
    #     prefix is prepended by this routine.  So, if the Scale attribute
    #     is "user.mything," then udefattr paramater is "mything"
    #   defaultVal - (optional) if the caller has a default value they
    #     want to be assigned to the tag's value, then they can supply
    #     that default value, else it's "None."
    ####################################################################
    def getscaleudef(self, udefAttr, myPath, defaultVal="None"):
      retval = defaultVal

      self.logger.debug("getscaleudef(): Retrieving attribute <" + udefAttr
          + "> from " + myPath)

      scaleUdefAttr = "user." + udefAttr.strip()
      cmd = "/usr/lpp/mmfs/bin/mmlsattr -n " + scaleUdefAttr + " \"" + myPath + "\""
      self.logger.debug("cmd = <" + cmd + ">")
      status, output = commands.getstatusoutput(cmd)

      if status != 0 :
        self.logger.debug("bad file name:" + myPath)
        self.logger.debug("mmlsattr status =" + str(status))
        self.logger.debug("mmlsattr output =" + str(output))
        return retval

      olist = output.splitlines()
      olen = len(olist)

      if (olen < 2):
        self.logger.debug("bad path name:" + myPath)
        return retval
      else:
        output = olist[1]

      # Parse output
      valueSentinel = ":"
      ndx = output.find(valueSentinel)

      # If invalid mmlsattr output, we're done.
      if ndx <= 0 :
        self.logger.debug("sentinel (" + valueSentinel + ") not found.")
        return retval

      # If attribute, e.g., user.project, is found, possible output is:
      # user.project:         No such attribute
      # OR
      # user.project:         "someValue"
      tmp = output[ndx:]
      # May be unnecessary check as above test for cmd status probably
      # catches this.
      if (tmp.find("No such attribute") >= 0):
        self.logger.debug(": No such attribute")
        self.logger.debug("returning: <" + retval )
        return retval

      # Move to leading double quote, then just past it
      ndx = tmp.find('"')
      if ndx < 0 :
        self.logger.debug( valueSentinel + " value not found")
        return retval
      tmp = tmp[ndx+1:]

      # Find end of value
      ndx = tmp.find('"')
      if ndx < 0 :
        self.logger.debug("no value found for " + valueSentinel)
        return retval

      retVal = tmp[:ndx]

      self.logger.debug("retVal=" + retVal)
      return str(retVal)


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
# Scale user-defined metadata  python Agent - main function         #
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
    agent = ScaleActionAgent(registration_info)

    # Start agent:
    # - register agent to Spectrum Discover
    # - get Kafka certificates from Spectrum Discover
    # - instantiate Kafka producer and consumer
    # - start processing Kafka messages (on_agent_message)
    agent.start()
