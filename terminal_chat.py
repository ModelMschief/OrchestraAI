import requests
import uuid
import sys

API_URL = "http://127.0.0.1:8001/api"

def main():
    print("=====================================================")
    print(" 🚀 OrchestraAI Interactive Terminal Client")
    print("=====================================================\n")
    
    # Use the keys from our latest automated E2E test as defaults
    default_key = "sk-orc-11f7f05510306eae7948e9572f8e1670"
    default_agent = "7"

    api_key = input(f"Enter your Platform API Key (Press enter for default '{default_key}'): ").strip()
    if not api_key:
        api_key = default_key
        
    agent_id = input(f"Enter Agent ID (Press enter for default '{default_agent}'): ").strip()
    if not agent_id:
        agent_id = default_agent
        
    print(f"\n[Connecting to Agent {agent_id} via Platform API...]")
    
    # Generate unique session/customer ID for this terminal instance so it remembers context!
    customer_id = "terminal_user_" + str(uuid.uuid4())[:8]
    session_id = "session_" + str(uuid.uuid4())[:8]
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Small ping to verify the server is alive
    try:
        requests.get(f"{API_URL}/health")
    except requests.exceptions.ConnectionError:
        print("\n[ERROR] Could not connect to the server!")
        print("Make sure the OrchestraAI backend server is running on http://127.0.0.1:8001")
        sys.exit(1)

    print("\n✅ Connected! Type 'quit' or 'exit' to stop.")
    print(f"Customer ID: {customer_id} | Session ID: {session_id}")
    print("-" * 60)
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
            
        if user_input.lower() in ["quit", "exit"]:
            print("\nEnding session. Goodbye!")
            break
        if not user_input:
            continue
            
        payload = {
            "agent_id": int(agent_id),
            "customer_id": customer_id,
            "session_id": session_id,
            "content": user_input
        }
        
        try:
            response = requests.post(f"{API_URL}/external/chat", headers=headers, json=payload)
            if response.status_code == 200:
                answer = response.json().get("answer", "[No answer returned]")
                print(f"\n🤖 Agent: {answer}")
            else:
                print(f"\n❌ [Error {response.status_code}]: {response.text}")
                
        except requests.exceptions.RequestException as e:
            print(f"\n❌ [Connection Error]: {e}")
            print("Make sure the OrchestraAI backend server is running on http://127.0.0.1:8001")

if __name__ == "__main__":
    main()
