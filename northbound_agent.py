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


# fetch chat history for LLM context
def get_chat_history():
    try: 
        with open(f'logs/{CHAT_HISTORY_FILE}', 'r') as f:
            chat_history = json.load(f)
        return chat_history
    except Exception as e: 
        print(f'Error retrieving chat history: {e}')
        return None


def main():
    decision = ''
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
            

if __name__ == "__main__":
    main()