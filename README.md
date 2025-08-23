# PatchHunter

## Description

PatchHunter is a Python application which implements intent-based networking using a large language model (LLM). It integrates Claude Sonnet 4 within the decision-making process of an SDN network by receiving user input and a snapshot of the current state of the network in order to diagnose relevant network problems as well as propose and implement changes in the SDN controller. The objective is to simplify and automate network management by allowing human operators to interact with the network using natural language, enabling faster troubleshooting and action implementation, intelligent decision-making, and improved discovery and control in dynamic SDN environments. 



## Main Features

#### **Dynamic Network State Retrieval**
Gathers real-time data about the network from the SDN controller, including MAC tables, port statistics, stop port states, flow tables, and host-to-switch mappings. This allows the system to maintain an up-to-date snapshot view of the network state for monitoring and decision-making. 

#### **LLM-Powered Network Diagnostics**
Anomaly detection and response. Uses Claude Sonnet 4 (20250514) to detect signs of congestion, port failures, and unreachable hosts in the network and helps to suggest steps to take to verify the issue. 

#### **Intent-Based Inference**
Translates natural language intents from the network engineer into SDN controller -compatible actions and implements them in the network. The system can interpret the network engineer’s high-level goal, e.g. “Reconfigure flows to block all communication between hosts h3 and h4” and translate it into concrete network objectives. The system interprets the goal and aligns it with the network’s current state.

#### **Controller-Side Action Implementation**
Executes LLM-generated actions directly within the SDN controller using OpenFlow commands. This includes installing and removing flows, modifying and monitoring port states, checking host locations, and tracing the route that data packets take to arrive at their destinations.



## How Does It Work?
- **Network state retrieval:** When the user has requested action, the current state of the network is retrieved for analysis. A JSON object containing the switches, MAC tables, port statistics, port descriptions, stp port states, flow tables, and host-to-switch mappings is retrieved and sent to the LLM for analysis in the first query.
- **Network topology retrieval:** Similarly to the network state data, the network topology, consisting of a static JSON file, is retreived, parsed, and also sent to the LLM along with the first query as contextual information.
- **Recommendation and decision-making:** The user intent, network state and topology data, and the general rules of SDN controller operations are combined to query for a formal diagnosis and recommendation for actionable steps to take to confirm or solve the problem.
- **Format validation:** A second query to the LLM is performed in order to ensure that the actionable output (a list of JSON objects) provided by the first query is precise and in the correct format. This is done to increase the consistency of the final LLM output and make sure that it can be understood and implemented by the SDN controller. It is an important step of the process as general-purpose LLMs, such as ChatGPT and Claude Sonnet, lack the specific fine-tuning for network management and may thus produce varying output, particularly when query prompts are large and contain larger quantities of necessary contextual data.
- **Action implementation:**  If actionable steps are suggested, the network engineer can review the recommendation and allow or deny the actions. If the actions are denied, the agent will return to wait for a new user input. If the user accepts the actions, they will be implemented in the SDN controller directly. 
- **Logging:** The network state snapshots are stored in the logs/ folder by timestamp.json for future monitoring and improvement. 



## Requirements, Installation & Running the App

### Requirements
The application requires **Mininet** and runs on **Python3** (Python 3.8.0 was used in development) 
Required libraries include: 
- anthropic v.0.60.0
- python-dotenv v.1.0.1
- requests v.2.32.4
- ryu v.4.34
- mininet v.2.3.0.dev6

The Python library requirements are also available in the `requirements.txt` file in the repository root folder. 


### Installation
1. Clone the repository in your local machine as follows: 
`git clone https://github.com/wannalina/networking-project.git`
2. Install the dependencies: 
`pip install -r requirements.txt`
3. Ensure that Mininet is up and running


### Running the App

1. **Start**
Move yourself to a separated environment, like comnetsemu.

2. **Mininet and topology initialization:** 
Use the following command: 
`sudo python3 mininet/topology.py`
This will initialize the Mininet network simulation, start the RYU controller, and build the static topology consisting of four switches and six hosts, with the links formed as follows: 
<img src="img/network_topo.png" alt="Network Topology" width="200"/>
Once the controller has finished initializing, test it using the `pingall` command to verify that all hosts can reach each other.

3. **Initialize the main application**
Use the following command to initialize PatchHunter: 
`sudo python3 northbound_agent.py`

4. **Ask questions and perform actions**
Observe that the command line interface of `northbound_agent.py`, the program asks for user input (intent). 
On this command line, enter a question or a command, for example, "Please disable all ports on switch 1". 
Then, review the agent's repsonse. If the proposed action corresponds to what you want to achieve, reply "yes" to the agent to confirm and execute the action.

5. **Test the action**
If you used the above example, you can test the change using one of the following two methods: 
- **Use the `pingall` function in the Mininet terminal.** Because the topology links are configured such that host 1 only connects to switch 1 (and no other hosts connect directly to this switch), disabling the ports of switch 1 should effectively cut off host 1 from the rest of the network. This means that host 1 should not be able to communicate with any other host and the `pingall` table should look like this:
<img src="img/pingall_table.png" alt="Pingall Table" width="400"/>

- **Ask PatchHunter to check the status of all ports on switch 1.** In this case, the LLM response should suggest a `check_port_status` action, to which you must reply "yes" to execute. The final response should return `state: 1` for allports on the switch or otherwise indicate in natural language that the port is in state `down`.

6. **To exit the program**, stop the PatchHunter application by typing "exit" on the `northbound_agent.py` command line interface. Then stop the Mininet instance using the following command: 
`exit`
Finally, clear and clean up any leftover Mininet network states and processes using the command: 
`sudo mn -c`




