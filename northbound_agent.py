from dotenv import load_dotenv
import os
import anthropic
import requests
from datetime import datetime
import json


load_dotenv()
API_KEY = os.getenv("API_KEY")
CONTROLLER_URL = os.getenv("CONTROLLER_API_URL")

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
          However, if the suitable action in "host_location"or "trace_route", only provide the answer as a concise sentence by analyzing only the network topology. Do not create an instruction object.
        - Ensure that each action is precise and complete. The object must solve the user intent in its entirety.

        - Avoid recommending flows on stp-blocked ports, assuming MAC-to-port mappings that do not exist, and issuing actions to non-existent datapaths.


        - The network topology is a description of the static switches, hosts, and links within the network  ("s" refers to switch and "h" refers to host):
            {network_topology}

        - The network state shows switches, host tables, mac tables, port stats, stp port states, port description stats, and flow tables used for network diagnosis and context: 
            {network_state}

        - The user intent provides the objective that we want to achieve with the produced actions: 
            {user_intent}


        - Internally analyze and understand the user intent, network topology, and current network state.
        - Internally vet all suggested actions to quarantee that they are complete and precisely address the user intent.
        - Optimize for clarity, concise presentation, and practical value.


        - Return the results as a properly formatted list of JSON objects with the following format:
        ```json 
        [
            {{ "action": "install_flow", "switch": 1, "out_port": 1, "src_mac": "00:00:00:00:00:01", "dst_mac": "00:00:00:00:00:04" }},
            {{ "action": "delete_flow", "switch": 1 }},
            {{ "action": "block_port", "switch": 2, "port": 4 }},
            {{ "action": "unblock_port", "switch": 3, "port": 4 }},
            {{ "action": "check_port_status", "switch": 2, "port": 5 }},
            {{ "action": "trace_route", "src_mac": "00:00:00:00:00:02", "dst_mac": "00:00:00:00:00:06" }}
        ]
        ```
        OR
        "Host 00:00:00:00:00:01 is located at switch 1."
        OR
        "Packets from h4 to h6 take the route h4 -> s3 -> s4 -> h6"

        - Task is complete when a list of correct and complete JSON action objects is returned in the specified format (including datatypes), and validation has confirmed full compliance with all requirements. 
    """

    print("Processing decision query...")
    query_res = perform_query(prompt)

    try:
        # extract JSON object from response
        if "```json" in query_res:
            action = query_res.split("```json")[1].split("```")[0]
            return json.loads(action), True

        return query_res, False
    except Exception as e: 
        print(f'Failed to parse JSON object from query response.')
        return None


def build_confirmation_query(intent, json_object):
    prompt = f"""
        # Role
        Act as an SDN orchestration validator that checks whether a proposed controller action JSON object correctly matches the network engineer’s intent.

        # Task
        Verify that the given JSON object:  
        - Contains **all required fields** for the specified action type.  
        - Contains **no extra or invalid fields**.  
        - Adheres strictly to the allowed schema for that action.  
        If the object is valid, return it unchanged. If it is invalid, return a corrected JSON object that complies with the schema and intent.

        # Context
        **Engineer’s intent:**  
        {intent}  

        **Proposed controller action (JSON):**  
        {json_object}  

        # Reasoning (checklist; do this internally)
        - Identify which action type is intended.  
        - Match the object’s fields against the schema for that action.  
        - Ensure correct field names, types, and required attributes.  
        - Remove any disallowed attributes.  
        - If attributes are missing, add them with values derived from the intent.  
        - Preserve JSON list structure — every response must be wrapped in a list.  

        # Allowed action schemas
        - **install_flow**  
        ```json
        [
            {{
                "action": "install_flow", 
                "switch": <int>,
                "out_port": <int>,
                "src_mac": "<MAC>", 
                "dst_mac": "<MAC>", 
                "actions": [{{"type": "output", "port": <int>}}]
            }}
        ]
        ```

        - **delete_flow**
        ```json
        [
            {{
                "action": "delete_flow",
                "switch": <int>
            }}
        ]
        ```

        - **block_port / unblock_port**
        ```json
        [
            {{
                "action": "block_port" or "unblock_port", 
                "switch": <int>, 
                "port": <int>
            }}
        ]  
        ```

        - **check_port_status**
        ```json
        [
            {{
                "action": "check_port_status",
                "switch": <int>,
                "port": <int>
            }}
        ]
        ```

        - **host_location**
        ```json
        [
            {{
                "action": "host_location", 
                "mac": "<MAC>"
            }}
        ]
        ```

        - ** trace_route**
        ```json
        [
            {{
                "action": "trace_route", 
                "src_mac": "<MAC>", 
                "dst_mac": "<MAC>"
            }}
        ]
        ```

        # Output format
        Return only valid JSON (no prose, no commentary, no code fences). It must begin with ```json and end in ```.
        - The object must be enclosed in a JSON list even if there is only one action.

        # Stop conditions
        - Do not add comments, explanations, or extra formatting.
        - Do not output fields not listed in the schema.
        - Task is complete when the JSON object matches both the engineer’s intent and the allowed schema.
    """

    print("Processing confirmation query...")
    query_res = perform_query(prompt)

    try:
        # extract JSON object from response
        if "```json" in query_res:
            action = query_res.split("```json")[1].split("```")[0]
            return json.loads(action)

        return None
    except Exception as e: 
        print(f'Error with the confirmation query: {e}')
        return None


# POST action to controller and implement
def apply_action(action): 
    # post to controller
    res = requests.post(f'{CONTROLLER_URL}/intent/implement', json=action)
    response = res.json()

    # print response in readable format
    print("\n\nController response:\n\n")
    for reply in response.get("results", []):
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

        action, is_json = build_query(user_intent, topology, network_state)

        if action and is_json: 
            action = build_confirmation_query(user_intent, action)
            doAction = input("\n\nEnter 'yes' to execute decision (otherwise return to start):\n")

            # if action allowed, save to history and execute
            if doAction.lower() == 'yes':
                apply_action(action)
            else: 
                print("No action available or action not needed.")

if __name__ == "__main__":
    main()
