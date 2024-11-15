from quart import Quart, render_template, request, jsonify
from quart_cors import cors
from anthropic import Anthropic
import os
import sys
import re
import traceback

# Initialize Quart app
app = Quart(__name__)
app = cors(app)
anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Force flush of print statements
sys.stdout.flush()

# Add at top with other globals
APPROVAL = 25  # Starting value
SYSTEM_PROMPT = None  # Initialize as None
STORY_CONTENT = None  # Initialize as None
CONVERSATION_HISTORY = []  # Initialize as empty list
CUMULATIVE_SCORE = 0
CURRENT_ROUTE = "starting route"
TRIGGERED_GATES = set()  # Keep track of which gates have been triggered
ACTIVE_BRANCH_CONTENT = set()  # Store active branch content strings

def load_story_components():
    components = {}
    story_dir = 'story'
    
    try:
        print("\n=== LOADING FILES ===", flush=True)
        system_prompt_path = os.path.join(story_dir, 'system_prompt.txt')
        with open(system_prompt_path, 'r') as file:
            components['system_prompt'] = file.read().strip()
            print("✓ Loaded system_prompt.txt", flush=True)
            
        file_order = ['lore.txt', 'prompt.txt', 'scenes.txt']
        story_content = []
        route_gates = []
        
        for filename in file_order:
            file_path = os.path.join(story_dir, filename)
            if os.path.exists(file_path):
                with open(file_path, 'r') as file:
                    content = file.read()
                    
                    if filename == 'scenes.txt':
                        import json
                        import re
                        
                        print("\n=== PROCESSING SCENES.TXT ===", flush=True)
                        print("Original content:", flush=True)
                        print(content, flush=True)
                        
                        # Extract and remove gate blocks
                        gate_blocks = re.findall(r'START_ROUTE_GATE\s*(.*?)\s*END_ROUTE_GATE', 
                                               content, re.DOTALL)
                        clean_content = re.sub(r'START_ROUTE_GATE.*?END_ROUTE_GATE', '', 
                                             content, flags=re.DOTALL).strip()
                        
                        print("\nCleaned content:", flush=True)
                        print(clean_content, flush=True)
                        
                        story_content.append(clean_content)
                        
                        print("\nExtracted gate blocks:", flush=True)
                        for block in gate_blocks:
                            print(block, flush=True)
                            try:
                                gates = json.loads(block)
                                if isinstance(gates, dict) and 'route_gates' in gates:
                                    route_gates.extend(gates['route_gates'])
                            except json.JSONDecodeError:
                                print(f"Warning: Invalid JSON in {filename}", flush=True)
                    else:
                        story_content.append(content.strip())
                    print(f"✓ Loaded {filename}", flush=True)
        
        components['story_content'] = "\n\n".join(story_content)
        components['route_gates'] = route_gates
        
        print("\n=== FINAL COMPONENTS ===", flush=True)
        print("\nSTORY_CONTENT:", flush=True)
        print(components['story_content'], flush=True)
        print("\nROUTE_GATES:", flush=True)
        print(json.dumps(components['route_gates'], indent=2), flush=True)
        print("=== FINISHED LOADING ===\n", flush=True)
        
    except Exception as e:
        print(f"ERROR loading files: {e}", flush=True)
        return None
    
    return components

def load_evaluator_prompt():
    try:
        with open('story/evaluator_prompt.txt', 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        print(f"Error loading evaluator prompt: {e}", flush=True)
        return None

# Initialize prompts
EVALUATOR_SYSTEM_PROMPT = load_evaluator_prompt()

# Initialize story components and send to Claude
print("\n=== STARTING APP ===", flush=True)
story = load_story_components()
if story:
    SYSTEM_PROMPT = story['system_prompt']
    STORY_CONTENT = story['story_content']
    ROUTE_GATES = story['route_gates']
    
    print("\n=== SENDING TO CLAUDE ===", flush=True)
    print("1. System Prompt:", flush=True)
    print(SYSTEM_PROMPT, flush=True)
    print("\n2. Combined Story Content:", flush=True)
    print(STORY_CONTENT, flush=True)
    
    # Initialize conversation history with combined story content
    CONVERSATION_HISTORY = [{
        "role": "user",
        "content": "This is my original creative work:\n\n" + STORY_CONTENT
    }]
    
    # Send first message to Claude
    try:
        initial_response = anthropic.messages.create(
            messages=CONVERSATION_HISTORY,
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            system=SYSTEM_PROMPT
        )
        print("\n=== CLAUDE'S INITIAL RESPONSE ===", flush=True)
        print(initial_response.content[0].text, flush=True)
        
        # Add Claude's response to history
        CONVERSATION_HISTORY.append({
            "role": "assistant",
            "content": initial_response.content[0].text
        })
        
        # Automatically send "Start the story"
        CONVERSATION_HISTORY.append({
            "role": "user",
            "content": "Start the story"
        })
        
        # Send second message with full history
        start_response = anthropic.messages.create(
            messages=CONVERSATION_HISTORY,
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            system=SYSTEM_PROMPT
        )
        print("\n=== CLAUDE'S START STORY RESPONSE ===", flush=True)
        print(start_response.content[0].text, flush=True)
        
        # Add start response to history
        CONVERSATION_HISTORY.append({
            "role": "assistant",
            "content": start_response.content[0].text
        })
        
    except Exception as e:
        print(f"ERROR: {e}", flush=True)

def parse_score(response_text):
    try:
        # Look for "Score: XX" in the text
        import re
        score_match = re.search(r'Score: (-?\d+)', response_text)
        if score_match:
            return int(score_match.group(1))
        return None  # Return None if no score found
    except Exception as e:
        print(f"Error parsing score: {e}", flush=True)
        return None

def check_response_format(response_text):
    # Look for a numbered list
    import re
    numbered_items = re.findall(r'\d\.', response_text)
    return len(numbered_items) >= 3

def check_route_state(cumulative_score):
    """Check and update route state based on cumulative score"""
    global CURRENT_ROUTE, CONVERSATION_HISTORY, TRIGGERED_GATES, ACTIVE_BRANCH_CONTENT
    route_changed = False
    gate_message = None
    
    # Check each route gate that hasn't been triggered yet
    for gate in ROUTE_GATES:
        threshold = gate['threshold']
        if threshold not in TRIGGERED_GATES:
            condition = f"{cumulative_score}{threshold}"
            try:
                if eval(condition):
                    # Add branch content to active set
                    ACTIVE_BRANCH_CONTENT.add(gate['branch_content'])
                    
                    # Update first message in conversation history
                    if CONVERSATION_HISTORY and len(CONVERSATION_HISTORY) > 0:
                        branch_text = "\n\n".join(ACTIVE_BRANCH_CONTENT)
                        CONVERSATION_HISTORY[0]['content'] = f"This is my original creative work:\n\n{STORY_CONTENT}\n\n{branch_text}"
                    
                    route_changed = True
                    CURRENT_ROUTE = f"gate_{threshold}"
                    gate_message = f"Story Branch Triggered: {gate['branch_content']}"
                    TRIGGERED_GATES.add(threshold)
                    
                    print(f"Route gate triggered: {threshold}", flush=True)
                    print(f"Added branch content: {gate['branch_content']}", flush=True)
            except Exception as e:
                print(f"Error evaluating route gate: {e}", flush=True)
    
    return {
        'message': gate_message if gate_message else "no route change",
        'changed': route_changed
    }

async def evaluate_response(conversation_history):
    global CUMULATIVE_SCORE
    
    try:
        # Format the full conversation history for evaluation
        eval_messages = [{
            "role": "user",
            "content": f"""Please evaluate the full conversation history, focusing on Jun's response in the most recent interaction:

Full Conversation:
{chr(10).join([f"{msg['role'].upper()}: {msg['content']}" for msg in conversation_history[:-1]])}

Most Recent Response:
{conversation_history[-1]['content']}"""
        }]
        
        # Send to evaluator Claude without await
        evaluation = anthropic.messages.create(
            messages=eval_messages,
            model="claude-3-5-sonnet-20241022",
            max_tokens=512,
            system=EVALUATOR_SYSTEM_PROMPT
        )
        
        # Parse score and approval from response
        eval_text = evaluation.content[0].text
        
        score_match = re.search(r'Score: ([-+]?\d+)', eval_text)
        approval_match = re.search(r'Approval: (\d+)', eval_text)
        
        if score_match:
            score = int(score_match.group(1))
            CUMULATIVE_SCORE += score
            
            # Check route state after updating cumulative score
            route_status = check_route_state(CUMULATIVE_SCORE)
            
            return {
                'evaluation': eval_text,
                'score': score,
                'cumulative_score': CUMULATIVE_SCORE,
                'approval': int(approval_match.group(1)) if approval_match else None,
                'route_state': route_status['message'],
                'route_changed': route_status['changed']
            }
    except Exception as e:
        print(f"Evaluation error: {e}", flush=True)
        return None

@app.route('/')
async def home():
    return await render_template('index.html')

@app.route('/chat', methods=['POST'])
async def chat():
    global CONVERSATION_HISTORY, ACTIVE_BRANCH_CONTENT
    try:
        data = await request.get_json()
        CONVERSATION_HISTORY = data['messages']
        
        # Reapply any active branch content to first message
        if ACTIVE_BRANCH_CONTENT and len(CONVERSATION_HISTORY) > 0:
            branch_text = "\n\n".join(ACTIVE_BRANCH_CONTENT)
            CONVERSATION_HISTORY[0]['content'] = f"This is my original creative work:\n\n{STORY_CONTENT}\n\n{branch_text}"
        
        print("\nSending to Story Claude...", flush=True)
        # Create message without await
        response = anthropic.messages.create(
            messages=CONVERSATION_HISTORY,
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            system=SYSTEM_PROMPT
        )
        
        print("\nReceived Story Claude response", flush=True)
        # Get Claude's response text
        response_text = response.content[0].text
        print("Response text:", response_text, flush=True)
        
        # Update history with Claude's response
        CONVERSATION_HISTORY.append({
            "role": "assistant",
            "content": response_text
        })
        
        print("\nSending to Evaluator Claude...", flush=True)
        # Evaluate the response
        evaluation = await evaluate_response(CONVERSATION_HISTORY)
        print("Evaluation result:", evaluation, flush=True)
        
        print("\n=== SENDING RESPONSE TO CLIENT ===", flush=True)
        return jsonify({
            'response': response_text,
            'evaluation': evaluation
        })
        
    except Exception as e:
        print(f"\nServer Error in /chat: {str(e)}", flush=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/get_history')
async def get_history():
    return jsonify({
        "history": CONVERSATION_HISTORY
    })

@app.route('/restart', methods=['POST'])
async def restart():
    global CUMULATIVE_SCORE, CURRENT_ROUTE, CONVERSATION_HISTORY, TRIGGERED_GATES, ACTIVE_BRANCH_CONTENT
    CUMULATIVE_SCORE = 0
    CURRENT_ROUTE = "starting route"
    TRIGGERED_GATES.clear()
    ACTIVE_BRANCH_CONTENT.clear()  # Clear branch content on restart
    
    # Reset conversation history to ensure no leftover branch content
    CONVERSATION_HISTORY = []
    
    try:
        data = await request.get_json()
        # Clear history and reload story
        CONVERSATION_HISTORY = []
        story = load_story_components()
        
        if story:
            SYSTEM_PROMPT = story['system_prompt']
            STORY_CONTENT = story['story_content']
            ROUTE_GATES = story['route_gates']
            
            # Initialize with story content
            CONVERSATION_HISTORY = [{
                "role": "user",
                "content": "This is my original creative work:\n\n" + STORY_CONTENT
            }]
            
            try:
                # Send first message to Claude
                initial_response = anthropic.messages.create(
                    messages=CONVERSATION_HISTORY,
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2048,
                    system=SYSTEM_PROMPT
                )
                
                # Add Claude's response to history
                CONVERSATION_HISTORY.append({
                    "role": "assistant",
                    "content": initial_response.content[0].text
                })
                
                # Send "Start the story"
                CONVERSATION_HISTORY.append({
                    "role": "user",
                    "content": "Start the story"
                })
                
                # Get start response
                start_response = anthropic.messages.create(
                    messages=CONVERSATION_HISTORY,
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2048,
                    system=SYSTEM_PROMPT
                )
                
                # Add start response to history
                CONVERSATION_HISTORY.append({
                    "role": "assistant",
                    "content": start_response.content[0].text
                })
                
                return jsonify({"history": CONVERSATION_HISTORY})
                
            except Exception as e:
                print(f"ERROR: {e}", flush=True)
                return jsonify({"error": str(e)}), 500
                
        return jsonify({"error": "Failed to load story"}), 500
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("=== QUART APP STARTING ===", flush=True)
    import hypercorn.asyncio
    from hypercorn.config import Config
    import asyncio
    
    config = Config()
    config.bind = ["0.0.0.0:8080"]
    config.workers = 1
    
    asyncio.run(hypercorn.asyncio.serve(app, config))