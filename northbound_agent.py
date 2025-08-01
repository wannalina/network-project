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


# store previous action in chat history
def save_chat_history(action):
    chat_entry = {
        "response": action
    }

    # load existing entries
    if os.path.exists(f'logs/CHAT_HISTORY_FILE'):
        try:
            with open(f'logs/CHAT_HISTORY_FILE', 'r') as f:
                history = json.load(f)
                if not isinstance(history, list):
                    history = []
        except json.JSONDecodeError:
            history = []
    else:
        history = []

    # add new entry to list
    history.append(chat_entry)

    try:
        # add back to json file with new entry
        with open(CHAT_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print("Error saving chat history:", e)


# fetch chat history for LLM context
def get_chat_history():
    try: 
        with open(f'logs/{CHAT_HISTORY_FILE}', 'r') as f:
            chat_history = json.load(f)
        return chat_history
    except Exception as e: 
        print(f'Error retrieving chat history: {e}')
        return None

# delete LLM chat history upon shutdown
def delete_chat_history():
    try:
        if os.path.exists(CHAT_HISTORY_FILE):
            with open(CHAT_HISTORY_FILE, 'w') as f:
                f.truncate(0)
            print("Chat history cleared.")
        else:
            print("Chat history file does not exist.")
    except Exception as e:
        print("Error clearing chat history:", e)


# perform LLM query based on given prompt
def perform_query(prompt):
    try: 
        # send query to claude
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=20000,
            temperature=0.7,
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
def build_query(user_intent, network_topology, network_state, chat_history):
    prompt = f"""
        You are an SDN (Software Defined Networking) orchestration assistant that interprets user intents and translates them into actionable instructions for an SDN controller. You are currently working with a Ryu-based OpenFlow 1.3 controller managing a Mininet topology using Spanning Tree Protocol (STP) for loop prevention. The controller supports flow installation, port state modification, and host tracking.

        You will be given:

        1. The current **network topology** (including switches, hosts with IP and MAC addresses, and links)
        2. The current **network state** (including datapath IDs, STP config, port statistics, flow tables, etc.)
        3. The **chat history** between the user and the SDN system
        4. The current **user intent** (e.g. block traffic, verify host location, configure port, install flow, etc.)

        Your task is to:
        - Carefully analyze the network topology and state
        - Synthesize *all relevant details* (host/switch locations, port states, MAC learning, etc.)
        - Interpret the **user intent accurately**
        - Produce a minimal and precise **action instruction object** (in JSON format) that can be sent to the SDN controller for execution

        Be cautious to avoid:
        - Recommending flows on STP-blocked ports
        - Assuming MAC-to-port mappings that do not exist
        - Issuing actions on non-existent datapaths or disconnected hosts

        ### Step-by-step reasoning and validation is required before suggesting any instruction.

        ---

        #### Network Topology:
        ```json
        {{{network_topology}}}
        ```

        ### Network State:
        ```json
        {{{network_state}}}
        ```

        ### Chat History:
        ```json
        {{{chat_history}}}
        ```

        ### User Intent:
        {{{user_intent}}}

        ---

        Now, based on the above information:
        1. Reason through the current state of the network
        2. Determine if the user's request is valid and can be fulfilled given current constraints
        3. If it is valid, return a JSON object representing the exact action(s) the SDN controller should perform
        4. If it is invalid or incomplete, return a structured explanation with what is missing or inconsistent

        Output format example:
        ```json 
        [
            {{
                "action": "install_flow",
                "switch": "0000000000000001",
                "src_mac": "00:00:00:00:00:01",
                "dst_mac": "00:00:00:00:00:04",
                "out_port": 2
            }}
        ]
        ```
        OR (if the intent is invalid):
        ```json
        {
            "error": "Cannot fulfill request — MAC 00:00:00:00:00:04 is not currently mapped to any known port in the network."
        }
        ```
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
        chat_history = get_chat_history()

        if topology and network_state and chat_history:
            action = build_query(user_intent, topology, network_state, chat_history)
        
        if action: 
            doAction = input("\nEnter 'yes' to execute decision (otherwise return to start)")

            # if action allowed, save to history and execute
            if doAction.lower() == 'yes':
                save_chat_history(action)
                apply_action(action)
            else: 
                print("No action available or action not needed.")

    delete_chat_history()

if __name__ == "__main__":
    main()