from flask import Flask, render_template, request, jsonify
from anthropic import Anthropic
import os
import sys

app = Flask(__name__)
anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Force flush of print statements
sys.stdout.flush()

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
    
    # Send to Claude immediately
    try:
        initial_response = anthropic.messages.create(
            messages=CONVERSATION_HISTORY,
            model="claude-3-sonnet-20240229",
            max_tokens=1000,
            system=SYSTEM_PROMPT
        )
        print("\n=== CLAUDE'S INITIAL RESPONSE ===", flush=True)
        print(initial_response.content[0].text, flush=True)
        
        # Add Claude's response to history
        CONVERSATION_HISTORY.append({
            "role": "assistant",
            "content": initial_response.content[0].text
        })
        
    except Exception as e:
        print(f"ERROR: {e}", flush=True)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        new_message = data.get('messages', [])[-1]  # Get just the new message
        
        # Add new message to history
        CONVERSATION_HISTORY.append(new_message)
        
        # Send complete history to Claude
        response = anthropic.messages.create(
            messages=CONVERSATION_HISTORY,  # Send all messages including initial story
            model="claude-3-sonnet-20240229",
            max_tokens=1000,
            system=SYSTEM_PROMPT
        )
        
        # Add Claude's response to history
        CONVERSATION_HISTORY.append({
            "role": "assistant",
            "content": response.content[0].text
        })
        
        return jsonify({"response": response.content[0].text})
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("=== FLASK APP STARTING ===", flush=True)
    app.run(debug=False)