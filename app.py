from flask import Flask, render_template, request, jsonify
from anthropic import Anthropic
import os
import sys

app = Flask(__name__)
anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Force flush of print statements
sys.stdout.flush()

# Add at top with other globals
APPROVAL = 25  # Starting value
SYSTEM_PROMPT = None  # Initialize as None
STORY_CONTENT = None  # Initialize as None
CONVERSATION_HISTORY = []  # Initialize as empty list

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

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    global APPROVAL, CONVERSATION_HISTORY, SYSTEM_PROMPT, STORY_CONTENT
    try:
        data = request.json
        new_message = data.get('messages', [])[-1]
        
        CONVERSATION_HISTORY.append(new_message)
        
        response = anthropic.messages.create(
            messages=CONVERSATION_HISTORY,
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            system=SYSTEM_PROMPT
        )
        
        response_text = response.content[0].text
        
        # Check if response is properly formatted
        if not check_response_format(response_text):
            print("ERROR: Improperly formatted Claude response", flush=True)
            
            # Reset conversation and reload story
            CONVERSATION_HISTORY = []
            story = load_story_components()
            if story:
                SYSTEM_PROMPT = story['system_prompt']
                STORY_CONTENT = story['story_content']
                
                # Reinitialize conversation with story content
                CONVERSATION_HISTORY = [{
                    "role": "user",
                    "content": "This is my original creative work:\n\n" + STORY_CONTENT
                }]
            
            return jsonify({
                "response": response_text + "\n\nERROR: Improperly formatted Claude response. Restarting story...",
                "approval": APPROVAL
            })
        
        # If properly formatted, continue as normal
        score = parse_score(response_text)
        if score is not None:
            APPROVAL = max(0, min(100, APPROVAL + score))
        
        CONVERSATION_HISTORY.append({
            "role": "assistant",
            "content": response_text
        })
        
        return jsonify({
            "response": response_text,
            "approval": APPROVAL
        })
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_history')
def get_history():
    return jsonify({
        "history": CONVERSATION_HISTORY
    })

@app.route('/restart', methods=['POST'])
def restart():
    global CONVERSATION_HISTORY
    
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

if __name__ == '__main__':
    print("=== FLASK APP STARTING ===", flush=True)
    app.run(debug=False)