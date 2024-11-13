from flask import Flask, render_template, request, jsonify
from anthropic import Anthropic
import os

app = Flask(__name__)
anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

INITIAL_PROMPT = """You are an intelligent programmer, powered by Claude 3.5 Sonnet. 
You are happy to help answer any questions that the user has (usually they will be about coding).
Please format your responses in markdown."""

@app.route('/')
def home():
    print("Home route accessed!")
    try:
        return render_template('index.html')
    except Exception as e:
        print(f"Error rendering template: {e}")
        return str(e), 500

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        messages = data.get('messages', [])
        
        # Extract the messages without the system prompt
        claude_messages = []
        for msg in messages:
            claude_messages.append({
                "role": "user" if msg["role"] == "user" else "assistant",
                "content": msg["content"]
            })
        
        try:
            response = anthropic.messages.create(
                messages=claude_messages,
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                system=INITIAL_PROMPT
            )
            return jsonify({"response": response.content[0].text})
        except Exception as e:
            print(f"Anthropic API error: {str(e)}")
            return jsonify({"error": str(e)}), 500
            
    except Exception as e:
        print(f"Server error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print(f"Current working directory: {os.getcwd()}")
    print("Server starting...")
    app.run(debug=True)