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
MAX_APPROVAL = 15
MIN_APPROVAL = -15

def load_story_components():
    components = {}
    story_dir = 'story'
    
    try:
        print("\n=== LOADING FILES ===", flush=True)
        # First load system prompt separately
        system_prompt_path = os.path.join(story_dir, 'system_prompt.txt')
        with open(system_prompt_path, 'r') as file:
            components['system_prompt'] = file.read().strip()
            print("✓ Loaded system_prompt.txt", flush=True)
            
        # Then load other story files in specific order
        file_order = ['lore.txt', 'prompt.txt', 'scenes.txt']
        story_content = []
        for filename in file_order:
            file_path = os.path.join(story_dir, filename)
            if os.path.exists(file_path):
                with open(file_path, 'r') as file:
                    content = file.read().strip()
                    story_content.append(content)
                    print(f"✓ Loaded {filename}", flush=True)
                    
        components['story_content'] = "\n\n".join(story_content)
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
    global CURRENT_ROUTE
    previous_route = CURRENT_ROUTE
    route_changed = False
    
    if cumulative_score >= MAX_APPROVAL:
        CURRENT_ROUTE = "high approval route"
        route_changed = True
    elif cumulative_score <= MIN_APPROVAL:
        CURRENT_ROUTE = "low approval route"
        route_changed = True
        
    if route_changed:
        return {
            'message': f"Route Change: {CURRENT_ROUTE}",
            'changed': True
        }
    return {
        'message': "no route change",
        'changed': False
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
    global CONVERSATION_HISTORY
    try:
        print("\n=== CHAT REQUEST RECEIVED ===", flush=True)
        data = await request.get_json()
        if not data or 'messages' not in data:
            print("Invalid request data", flush=True)
            return jsonify({'error': 'Invalid request data'}), 400
            
        print(f"Number of messages received: {len(data['messages'])}", flush=True)
        print("Last message:", data['messages'][-1], flush=True)
        
        # Update conversation history
        CONVERSATION_HISTORY = data['messages']
        
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
    global CUMULATIVE_SCORE, CURRENT_ROUTE
    CUMULATIVE_SCORE = 0
    CURRENT_ROUTE = "starting route"  # Reset route state
    try:
        data = await request.get_json()
        # Clear history and reload story
        CONVERSATION_HISTORY = []
        story = load_story_components()
        
        if story:
            SYSTEM_PROMPT = story['system_prompt']
            STORY_CONTENT = story['story_content']
            
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
    app.run(debug=False, port=5000)