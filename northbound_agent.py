from dotenv import load_dotenv
import os
import anthropic
import requests
from datetime import datetime
import json


load_dotenv()
API_KEY = os.getenv("API_KEY")
CONTROLLER_URL = os.getenv("CONTROLLER_URL")
CHAT_HISTORY_FILE = os.getenv("CHAT_HISTORY_FILE")

# init anthropic client (LLM)
client = anthropic.Anthropic(api_key=API_KEY)


# get network topology for LLM context
def get_network_topology():
    try: 
        # read topology from json file
        with open('mininet/topology.json', 'r') as f:
            topology = json.load(f)
        return topology
    except Exception as e:
        print(f'Error fetching network topology.json: {e}')
        return None


# get network state for LLM context
def get_network_state():
    try: 
        # get network state from controller
        res = requests.get(f'{CONTROLLER_URL}/intent/get-state')
        network_state = res.json()

        # log in json file
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f'logs/{timestamp}.json'

        if not os.path.exists('logs'):
            os.mkdir('logs')
        with open (log_filename, 'w') as log_file:
            json.dump(network_state, log_file, indent=2)

        return network_state
    except Exception as e: 
        print(f'Error fetching network state from controller: {e}')
        return None


# perform LLM query based on given prompt
def perform_query(prompt):
    try: 
        # send query to claude
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=20000,
            temperature=0,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        )

        # parse response
        full_reply = response.content[0].text
        print(full_reply)
        return full_reply
    except Exception as e: 
        print(f'Error querying LLM: {e}')
        return None


# build the query to get LLM response
def build_query(user_intent, network_topology, network_state):
    prompt = f"""
        Act as an SDN network expert focused on providing your colleague insturctions on managing an SDN network operated by an RYU simple switch stp controller.

        - Begin with a conscise checklist (2-5 bullets) of the steps you will follow to complete the task, focusing on high-level description rather than technical details.
        - Produce a precise action instruction object (in JSON format) that can be sent directly to the SDN controller for implementation in the network.
        - Ensure that each action is precise and complete. The object must solve the user intent in its entirety.

        - Avoid recommending flows on stp-blocked ports, assuming MAC-to-port mappings that do not exist, and issuing actions to non-existent datapaths.


        - The network topology is a description of the static switches, hosts, and links within the network  ("s" refers to switch and "h" refers to host):
            {network_topology}

        - The network state shows datapath IDs (switches), STP config, port statistics, flow tables, etc. used for network diagnosis and context: 
            {network_state}

        - The user intent provides the objective that we want to achieve with the produced actions: 
            {user_intent}


        - Internally analyze and understand the user intent, network topology, and current network state.
        - Internally vet all suggested actions to quarantee that they are complete and precisely address the user intent.
        - Optimize for clarity, concise presentation, and practical value.


        - Return the results as a properly formatted list of JSON objects with the following format:
        ```json 
        [
            {{ "action": "install_flow", "switch": "0000000000000001", "src_mac": "00:00:00:00:00:01", "dst_mac": "00:00:00:00:00:04", "in_port": 2 }},
            {{ "action": "delete_flow", "switch": 1 }},
            {{ "action": "block_port", "switch": 2, "port": 4 }},
            {{ "action": "unblock_port", "switch": 3, "port": 4 }},
            {{ "action": "request_port_stats" }}, 
            {{ "action": host_location", "mac": "00:00:00:00:00:01" }}
            {{ "action": "trace_route", "src_mac": "00:00:00:00:00:02", "dst_mac": "00:00:00:00:00:06" }}
        ]
        ```

        - Task is complete when a list of correct and complete JSON action objects is returned in the specified format, and validation has confirmed full compliance with all requirements. 
    """

    print("Processing query...")
    query_res = perform_query(prompt)

    try:
        # extract JSON object from response
        if "```json" in query_res:
            action = query_res.split("```json")[1].split("```")[0]
            return json.loads(action)

        return None
    except Exception as e: 
        print(f'Failed to parse JSON object from query response.')
        return None


# POST action to controller and implement
def apply_action(action): 
    # post to controller
    res = requests.post(f'{CONTROLLER_URL}/intent/implement', json=action)
    response = res.json()

    # print response in readable format
    print("\n\nController response:\n\n")
    for reply in response.get("status", []):
        print(f"{reply}\n")


def main():
    action = None
    while True:
        # get user intent
        user_intent = input("Enter your intent (or 'exit' to quit):\n")
        user_intent = user_intent.strip()

        if user_intent.lower() == 'exit':
            print("Exiting the intent agent...\n")
            break

        # get context for LLM
        topology = get_network_topology()
        network_state = get_network_state()

        action = build_query(user_intent, topology, network_state)
        
        if action: 
            doAction = input("\nEnter 'yes' to execute decision (otherwise return to start)")

            # if action allowed, save to history and execute
            if doAction.lower() == 'yes':
                apply_action(action)
            else: 
                print("No action available or action not needed.")

if __name__ == "__main__":
    main()