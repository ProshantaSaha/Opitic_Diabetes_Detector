Sample Action Agent
===================

The 'sample_action_agent.py' provides a python 2.7 based code, implementing a Sample Action Agent that connects to Spectrum Discover to process a policy.
Note that, this code is just for an illustration purpose on how to connect with the REST API endpoints exposed by Spectrum Discover, to configure an agent and to interact with the Kafka Work and Completion topics created for the agent and process the messages.  
This is not a production ready code and would need further enhancements with respect to error handling, performance and scalability.

Before starting this agent:
1. Following pre-requisites are met:
    * Spectrum Discover 2.x is installed and running in your environment.
    * Spectrum Discover host is reachable over the network from the node on which you want use to run the action agent.
    * Python 2.7 is installed on the system.
    * Python package manager `pip` is installed on the system.

2. Install the required python packages:
    ```sh
      $ pip install -r requirements.txt
    ```

3. Define environment variables as follows:
    ```sh
      $ export SPECTRUM_DISCOVER_HOST=https://<spectrum_discover_host>
      $ export AGENT_NAME=<agent_name>
      $ export AGENT_USER=<agent_user>
      $ export AGENT_USER_PASSWORD=<agent_user_password>
      $ export KAFKA_DIR=<directory_to_save_certificates>
      $ export LOG_LEVEL=<ERROR WARNING INFO DEBUG>
    ```

4. Now, you can start the sample agent, running the code as follows:
    ```sh
      $ chmod +x ./sample_action_agent.py

      $ ./sample_action_agent.py
    ```

## Implementation of Sample Action Agent

The _Sample Action Agent_ implementation is divided into two parts. The _base part_ is in the [agent_lib.py](./agent_lib.py) script that defines `ActionAgentBase` class with all the functionality that enables registration and communication with Spectrum Discover.
The _main part_ is in the [sample_action_agent.py](./sample_action_agent.py) script with an example how to implement custom agent with the use of `ActionAgentBase` class.

To implement an agent is simple. Only one function should be defined that accepts _Job Request Message_ (and agent instance) and returns _Job Response Message_ (`(agent, request_msg) -> response_msg`). This can be done by implementing `on_agent_message` method on a subclass derived from `ActionAgentBase` class

```py
class SampleActionAgent(ActionAgentBase):
  # (agent, request_msg) -> response_msg
  def on_agent_message(self, request_msg):
    ...
    return response_msg

agent = SampleActionAgent(logger)
```

or to instantiate `ActionAgentBase` directly and supply this function to agent's `subscribe` method as in [sample_action_agent_1.py](./sample_action_agent_1.py)

```py
# (agent, request_msg) -> response_msg
def process_agent_message(agent, request_msg):
  ...
  return response_msg

agent = ActionAgentBase(logger)

agent.subscribe(process_agent_message)
```
