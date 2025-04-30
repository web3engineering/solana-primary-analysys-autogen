import requests
import json
import base58
import asyncio  # Added missing import

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import StructuredMessage
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient

RPC_URL = "https://mainnet.helius-rpc.com/...."
OPENAI_KEY = "sk-proj-zj....."


def to_asciihex(data):
    return base58.b58decode(data).hex()


def get_first_transaction_for_address(address: str):
    """
    Get the first transaction for the given address by paginating through all signatures.
    Returns the transaction signature of the earliest transaction.
    """
    earliest_signature = None
    before_signature = None
    
    while True:
        # Prepare the request payload, using the 'before' parameter for pagination
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                address,
                {
                    "limit": 1000  # Maximum limit to reduce API calls
                }
            ]
        }
        
        # Add the 'before' parameter for pagination if we have a previous signature
        if before_signature:
            payload["params"][1]["before"] = before_signature
        
        # Make the request to the Solana RPC
        response = requests.post(RPC_URL, json=payload)
        signatures_data = response.json()
        
        # Check if we got any results
        if "result" not in signatures_data or not signatures_data["result"]:
            # No more transactions, we've reached the end
            break
        
        # Get the last signature in this batch (chronologically earliest in this batch)
        batch_signatures = signatures_data["result"]
        batch_earliest = batch_signatures[-1]["signature"]
        
        # Update our earliest known signature
        earliest_signature = batch_earliest
        
        # If we got fewer than the limit, we've reached the end
        if len(batch_signatures) < 1000:
            break
        
        # Otherwise, set the before_signature for the next iteration
        before_signature = batch_earliest
    
    return earliest_signature


def get_solana_transactions(address: str):
    """
    Get the latest 1000 instructions for the Solana program by address.
    Returns a list of instructions.

    :param address: The Solana program address to query.
    :return: {"data": bytes, "signature": str, "accounts": str[]}[]
    """
    # Step 1: Get the latest 100 transaction signatures for the address
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [
            address,
            {
                "limit": 50
            }
        ]
    }
    
    response = requests.post(RPC_URL, json=payload)
    signatures_data = response.json()
    
    if "result" not in signatures_data or not signatures_data["result"]:
        return []
    
    # Extract just the signatures from the response
    signatures = [item["signature"] for item in signatures_data["result"]]
    
    transactions_data = []
    
    # Step 2: Get transaction details for each signature
    for signature in signatures:
        tx_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0
                }
            ]
        }
        
        tx_response = requests.post(RPC_URL, json=tx_payload)
        tx_data = tx_response.json()
        
        if "result" not in tx_data or not tx_data["result"]:
            continue
            
        transaction = tx_data["result"]
        
        # Step 3: Process instructions (both top-level and internal)
        instructions_data = []
        
        # Process top-level instructions
        if "message" in transaction["transaction"] and "instructions" in transaction["transaction"]["message"]:
            for instruction in transaction["transaction"]["message"]["instructions"]:
                if address in instruction.get("accounts", []):
                    instructions_data.append({
                        "data": to_asciihex(instruction.get("data", "")),
                        "signature": signature,
                        "accounts": instruction.get("accounts", [])
                    })
        
        # Process internal instructions if available
        if "meta" in transaction and "innerInstructions" in transaction["meta"]:
            for inner_instructions_group in transaction["meta"]["innerInstructions"]:
                for inner_instruction in inner_instructions_group.get("instructions", []):
                    if address in inner_instruction.get("accounts", []):
                        instructions_data.append({
                            "data": to_asciihex(inner_instruction.get("data", "")),
                            "signature": signature,
                            "accounts": inner_instruction.get("accounts", [])
                        })
        
        # Add all found instructions for this transaction
        if instructions_data:
            transactions_data.extend(instructions_data)
    
    return transactions_data


model_client = OpenAIChatCompletionClient(
    model="gpt-4.1-2025-04-14",
    api_key=OPENAI_KEY,
)
tx_overview_agent = AssistantAgent(
    name="assistant",
    model_client=model_client,
    tools=[get_solana_transactions],
    reflect_on_tool_use = True,
    system_message="""\
Use the given tool to get latest instructions for the Solana program by address.

After receiving the raw instruction data, follow these steps:
1. Group the instructions by common patterns in the "data" field (focus on the first 8-10 characters as the function selector)
2. For each group:
   - Count how many instructions are in this group
   - Identify the pattern in the "data" field (the common prefix)
   - Note the number of accounts in the "accounts" field
   - Check if the same accounts appear in the same positions across instructions
   - Attempt to identify the probable purpose of this instruction type

Format your analysis in this structured Markdown:

## Solana Program Analysis Summary
- Total Instructions Analyzed: [number]
- Unique Instruction Types: [number]
- Most Common Instruction: [type with highest count]

## Detailed Instruction Groups

### Group 1: [Brief descriptor based on data pattern]
- **Count**: [number of instructions]
- **Data Pattern**: `[common hex prefix]...`
- **Accounts Required**: [number]
- **Common Accounts**: [list any accounts that appear frequently in the same position]
- **Probable Function**: [educated guess about what this instruction does]
- **Example Signature**: [one transaction signature from this group]

### Group 2: [Brief descriptor based on data pattern]
...

Ensure your analysis is comprehensive yet concise, focusing on patterns that might help understand the program's functionality.
"""
)

# Modified to use the correct format for messages with the agent
address = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
# print(get_solana_transactions("GYgLBPB1RM4V6ef1wSp3sLUcR8u9hnwYb6KpS3PMbonk"))

async def assistant_run_stream() -> None:
    # Option 1: read each message from the stream (as shown in the previous example).
    # async for message in agent.run_stream(task="Find information on AutoGen"):
    #     print(message)

    # Option 2: use Console to print all messages as they appear.
    await Console(
        tx_overview_agent.run_stream(task=f"Analyze the Solana program at address: {address}"),
        output_stats=True,  # Enable stats printing.
    )

asyncio.run(assistant_run_stream())

# 9527de9bd37c981a... - sell
# faea0d7bd59c13ec...  - buy
