"""
LLM Email Classifier using Google Gemini
=========================================

This module handles the AI-powered classification of emails to determine
if they are job application-related, and if so, extracts relevant information.

The main function is:
    extract_email_info_using_gemini(email_text) -> dict
    
This uses Google's Gemini model to:
    1. Classify if an email is job/internship related
    2. Extract company name, job title, and status if applicable

Why use an LLM for this?
    - Job emails come in many formats (LinkedIn, direct, recruiter, etc.)
    - Rule-based parsing would miss many variations
    - LLMs can understand context and extract structured data from unstructured text

Usage:
    from llm_evoke import extract_email_info_using_gemini
    
    result = extract_email_info_using_gemini(email_body_text)
    if result['is_job_application']:
        print(f"Company: {result['company_name']}")
        print(f"Position: {result['job_title']}")
"""

# =============================================================================
# IMPORTS
# =============================================================================

import os
import json
import re

from google import genai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# =============================================================================
# GEMINI CLIENT SETUP
# =============================================================================

# Initialize the Gemini client with API key from environment
# Make sure GOOGLE_API_KEY is set in your .env file
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

# Model to use for classification
# Gemini 2.5 Flash is fast and cost-effective for this use case
GEMINI_MODEL = "gemini-2.5-flash"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _create_empty_result(skipped: bool = False, reason: str = None) -> dict:
    """
    Create an empty result dictionary with all fields set to None.
    
    This is used when:
        - The email is not a job application (skipped=True)
        - An error occurred during processing
    
    Args:
        skipped: Whether this email was intentionally skipped
        reason: Human-readable explanation of why it was skipped
        
    Returns:
        Dictionary with all fields set to None and metadata
    """
    return {
        "company_name": None,
        "job_title": None,
        "status": None,
        "email_id": None,
        "is_job_application": False,
        "skipped": skipped,
        "reasoning": reason
    }


def _build_classification_prompt(email_text: str) -> str:
    """
    Build the prompt for the LLM to classify and extract email information.
    
    The prompt is structured to:
        1. First classify if it's a job-related email
        2. Then extract relevant details if applicable
    
    Args:
        email_text: The plain text content of the email
        
    Returns:
        Formatted prompt string for the LLM
    """
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
    return prompt


def _parse_llm_response(response_text: str) -> dict:
    """
    Parse the JSON response from the LLM.
    
    The LLM should return JSON, but sometimes it includes markdown formatting
    or extra text. This function tries multiple approaches to extract the JSON.
    
    Args:
        response_text: Raw text response from the LLM
        
    Returns:
        Parsed dictionary, or None if parsing fails
    """
    # Try 1: Direct JSON parse (ideal case)
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass
    
    # Try 2: Find JSON object in the text (LLM might add explanation text)
    match = re.search(r'\{[\s\S]+\}', response_text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    # Failed to parse
    return None


# =============================================================================
# MAIN EXTRACTION FUNCTION
# =============================================================================

def extract_email_info_using_gemini(email_text: str) -> dict:
    """
    Extract job application info from email text using Gemini LLM.
    
    This is the main function of this module. It sends the email text to
    Gemini, which classifies it and extracts relevant information.
    
    The function:
        1. Builds a prompt with the email text
        2. Sends it to Gemini for analysis
        3. Parses the JSON response
        4. Returns structured data about the email
    
    Args:
        email_text: The plain text body of the email to analyze
        
    Returns:
        Dictionary with the following keys:
            - is_job_application: bool - Whether this is a job-related email
            - reasoning: str - Explanation of the classification
            - company_name: str or None - Extracted company name
            - job_title: str or None - Extracted position title
            - status: str or None - Application status (applied/interview/offer/rejected)
            - email_id: str or None - Any reference number found
            
    Example:
        >>> result = extract_email_info_using_gemini("Thank you for applying to Google...")
        >>> result['is_job_application']
        True
        >>> result['company_name']
        'Google'
    """
    # Build the prompt for the LLM
    prompt = _build_classification_prompt(email_text)
    
    try:
        # Call the Gemini API
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        
        # Get the text from the response
        result_text = response.text
        
        # Parse the JSON response
        data = _parse_llm_response(result_text)
        
        if data is None:
            # Failed to parse response
            print("Warning: Could not parse LLM response as JSON")
            return _create_empty_result(skipped=True, reason="Failed to parse LLM response")
        
        # Check if LLM classified this as a job application
        is_job_app = data.get("is_job_application", False)
        reasoning = data.get("reasoning", "No reasoning provided")
        
        if not is_job_app:
            # Not a job application - return empty result with reason
            print(f"  Skipped: {reasoning}")
            return _create_empty_result(skipped=True, reason=reasoning)
        
        # It's a job application - extract and return the details
        print(f"  Job email detected: {reasoning}")
        
        return {
            "company_name": data.get("company_name"),
            "job_title": data.get("job_title"),
            "status": data.get("status"),
            "email_id": data.get("email_id"),
            "is_job_application": True,
            "reasoning": reasoning
        }
            
    except Exception as e:
        # Handle any errors (API errors, network issues, etc.)
        error_message = str(e)
        print(f"  Error: {error_message}")
        
        result = _create_empty_result(skipped=True, reason=f"Error: {error_message}")
        result["error"] = error_message
        return result


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    """
    When run directly, this script reads an email from email_for_llm.txt
    and processes it through the LLM for testing purposes.
    """
    print("=" * 50)
    print("  LLM Email Classifier Test")
    print("=" * 50)
    print()
    
    # Read the email content from file
    try:
        with open('email_for_llm.txt', 'r', encoding='utf-8') as file:
            email_contents = file.read()
    except FileNotFoundError:
        print("Error: email_for_llm.txt not found")
        print("Run fetch_emails.py first to generate a test email file")
        exit(1)
    
    print("Processing email through Gemini...")
    print()
    
    # Extract info and print the result
    result = extract_email_info_using_gemini(email_contents)
    
    print()
    print("Result:")
    print(json.dumps(result, indent=2))
