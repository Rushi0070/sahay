import os
import json
import re
from google import genai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up the Gemini client
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))


def extract_email_info_using_gemini(email_text):
    """
    Extract job application info from email text using Gemini LLM.
    
    First classifies if it's a job/internship email, then extracts details.
    Returns a dict with: company_name, job_title, status, email_id, is_job_application, reasoning
    """
    
    # The prompt asks LLM to classify AND extract in one call
    prompt = f"""Analyze this email and extract information:

STEP 1: Determine if this is a job or internship application email.
Consider these as job/internship emails:
- Application confirmations ("We received your application", "Thank you for applying")
- Interview invitations or scheduling
- Job/internship offers
- Rejection letters ("Unfortunately", "We decided to move forward with other candidates")
- Status updates about applications
- Recruiter outreach for specific positions

NOT job/internship emails:
- Marketing emails or promotions
- Surveys (like usability studies, feedback requests)
- Newsletter subscriptions
- Account notifications (password reset, login alerts)
- General promotional content
- Event invitations unrelated to job applications

STEP 2: If it IS a job/internship email, extract the details. If NOT, leave fields as null.

Return ONLY a JSON object with these fields:
{{
    "is_job_application": true or false,
    "reasoning": "brief 1-sentence explanation of your classification",
    "company_name": "company name" or null,
    "job_title": "position title" or null,
    "status": "applied" or "interview" or "offer" or "rejected" or "pending" or null,
    "email_id": "any reference number mentioned" or null
}}

Email:
{email_text}
"""

    try:
        # Call the Gemini API
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        
        # Get the text from the response
        result_text = response.text
        
        # Try to parse as JSON directly
        try:
            data = json.loads(result_text)
        except json.JSONDecodeError:
            # If that fails, find the JSON object in the text
            match = re.search(r'\{[\s\S]+\}', result_text)
            if match:
                data = json.loads(match.group(0))
            else:
                # No valid JSON found
                return _empty_result()
        
        # Check if LLM classified this as a job application
        is_job_app = data.get("is_job_application", False)
        reasoning = data.get("reasoning", "No reasoning provided")
        
        if not is_job_app:
            # Not a job application - skip it
            print(f"⏭️  Skipped: {reasoning}")
            return _empty_result(skipped=True, reason=reasoning)
        
        # It's a job application - extract the details
        print(f"✅ Job email detected: {reasoning}")
        
        return {
            "company_name": data.get("company_name"),
            "job_title": data.get("job_title"),
            "status": data.get("status"),
            "email_id": data.get("email_id"),
            "is_job_application": True,
            "reasoning": reasoning
        }
            
    except Exception as e:
        # If anything goes wrong, return empty result with error
        print(f"❌ Error: {str(e)}")
        result = _empty_result(skipped=True, reason=f"Error: {str(e)}")
        result["error"] = str(e)
        return result


def _empty_result(skipped=False, reason=None):
    """Return a dict with all fields set to None."""
    return {
        "company_name": None,
        "job_title": None,
        "status": None,
        "email_id": None,
        "is_job_application": False,
        "skipped": skipped,
        "reasoning": reason
    }


# Main execution
if __name__ == "__main__":
    # Read the email content from file
    with open('email_for_llm.txt', 'r', encoding='utf-8') as file:
        email_contents = file.read()
    
    # Extract info and print the result
    result = extract_email_info_using_gemini(email_contents)
    print(json.dumps(result, indent=2))
