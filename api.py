"""
FastAPI Backend for SyncApply
=============================

This module provides the REST API that the frontend uses to interact with
Gmail and the Supabase database. It handles:
    - Token verification for protected endpoints
    - Email fetching from Gmail (with parallel processing for speed)
    - Saving job applications to the database

Endpoints:
    GET  /                           - Health check
    GET  /api/emails                 - Fetch emails from Gmail
    GET  /api/emails/{email_id}      - Get a single email
    POST /api/applications/save/{id} - Save an email as application
    GET  /api/applications           - Get all saved applications
    POST /api/applications/process-latest - Process the latest email

Usage:
    python api.py
    
    Or with uvicorn directly:
    uvicorn api:app --reload
"""

# =============================================================================
# IMPORTS
# =============================================================================

import os
import asyncio
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

from fetch_emails import (
    GmailFetcher, 
    JobApplicationTracker, 
    format_email_for_llm,
    ExtractedEmail
)

# Load environment variables
load_dotenv()


# =============================================================================
# CONFIGURATION
# =============================================================================

# Check if we're running in production
# Set ENVIRONMENT=production in your deployment platform (Railway, etc.)
IS_PRODUCTION = os.getenv('ENVIRONMENT', 'development').lower() == 'production'

# Debug file path for logging email content during development
DEBUG_EMAIL_FILE = "email_for_llm.txt"

# Thread pool for parallel email fetching
# This allows us to fetch multiple emails concurrently
THREAD_POOL = ThreadPoolExecutor(max_workers=10)


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

# Create a single JobApplicationTracker instance to reuse across requests
# This avoids creating a new Supabase client connection on every request
job_tracker = JobApplicationTracker()


# =============================================================================
# FASTAPI APP SETUP
# =============================================================================

app = FastAPI(
    title="SyncApply API",
    description="Gmail Job Application Tracker API - Fetch emails and track job applications",
    version="1.0.0"
)

# Configure CORS to allow frontend connections
# In production, you should restrict this to your actual frontend domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",    # Local Vite dev server (alternate port)
        "http://localhost:5173",    # Default Vite dev server
        "*"                         # Allow all origins (for development)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class EmailResponse(BaseModel):
    """
    Response model for email data.
    
    This represents the email data sent to the frontend.
    It includes only the fields needed for display.
    """
    id: str
    subject: Optional[str]
    sender: Optional[str]
    date: Optional[str]
    snippet: str
    body_text: str


class ApplicationResponse(BaseModel):
    """
    Response model for a job application.
    
    Represents a saved job application from the database.
    """
    company_name: Optional[str]
    job_title: Optional[str]
    status: Optional[str]
    email_id: Optional[str]


class SaveResult(BaseModel):
    """
    Response model for save operations.
    
    Indicates whether the save was successful and provides a message.
    """
    success: bool
    message: str
    data: Optional[ApplicationResponse] = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def save_email_for_debugging(email: ExtractedEmail):
    """
    Save email content to a file for debugging purposes.
    
    Only runs in development mode to avoid unnecessary disk I/O in production.
    The file is gitignored so it won't be committed.
    
    Args:
        email: The extracted email to save
    """
    # Skip in production to improve performance
    if IS_PRODUCTION:
        return
        
    formatted = format_email_for_llm(email)
    with open(DEBUG_EMAIL_FILE, "w", encoding="utf-8") as f:
        f.write(formatted)
    print(f"Debug: Saved email to {DEBUG_EMAIL_FILE}")


def extract_email_to_response(extracted: ExtractedEmail) -> EmailResponse:
    """
    Convert an ExtractedEmail to an EmailResponse.
    
    Helper function to avoid code duplication when converting emails.
    
    Args:
        extracted: The extracted email data
        
    Returns:
        EmailResponse object ready for API response
    """
    return EmailResponse(
        id=extracted.id,
        subject=extracted.headers.get("Subject"),
        sender=extracted.headers.get("From"),
        date=extracted.headers.get("Date"),
        snippet=extracted.snippet,
        body_text=extracted.body_text
    )


async def verify_google_token(authorization: str = Header(...)) -> str:
    """
    Verify the Google OAuth token from the Authorization header.
    
    This is a dependency function that validates the Bearer token
    by checking it against Google's tokeninfo endpoint.
    
    Args:
        authorization: The Authorization header value (e.g., "Bearer <token>")
        
    Returns:
        The validated access token
        
    Raises:
        HTTPException: If token is missing, invalid, or expired
    """
    # Check that header has correct format
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    # Extract the token
    token = authorization.replace("Bearer ", "")
    
    # Verify with Google's tokeninfo endpoint
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://www.googleapis.com/oauth2/v1/tokeninfo",
            params={"access_token": token}
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return token


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """
    Health check endpoint.
    
    Use this to verify the API is running.
    """
    return {"status": "ok", "service": "SyncApply API"}


@app.get("/api/emails", response_model=list[EmailResponse])
async def get_emails(
    query: str = "in:inbox",
    max_results: int = 10,
    token: str = Depends(verify_google_token)
):
    """
    Fetch emails from Gmail with parallel processing.
    
    This endpoint retrieves emails matching the given query and returns
    them in a format suitable for display in the frontend. Emails are
    fetched in parallel for improved performance.
    
    Args:
        query: Gmail search query (same syntax as Gmail search box)
               Examples:
               - "in:inbox" - All inbox emails
               - "from:company.com" - Emails from specific domain
               - "subject:application" - Emails with 'application' in subject
        max_results: Maximum number of emails to return (1-100)
        token: Validated Google access token (injected by dependency)
        
    Returns:
        List of EmailResponse objects
    """
    try:
        # Create fetcher with the validated token
        fetcher = GmailFetcher(access_token=token)
        
        # Get list of message IDs matching the query
        messages = fetcher.fetch_email_list(query=query, max_results=max_results)
        
        if not messages:
            return []
        
        # Fetch all emails in parallel using thread pool
        # This is much faster than fetching one at a time
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(THREAD_POOL, fetcher.fetch_and_extract_email, msg["id"])
            for msg in messages
        ]
        extracted_emails = await asyncio.gather(*tasks)
        
        # Convert to response format
        emails = [extract_email_to_response(e) for e in extracted_emails]
        
        return emails
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/emails/{email_id}", response_model=EmailResponse)
async def get_email(
    email_id: str,
    token: str = Depends(verify_google_token)
):
    """
    Fetch a single email by its ID.
    
    Args:
        email_id: The Gmail message ID
        token: Validated Google access token (injected by dependency)
        
    Returns:
        EmailResponse with full email details
    """
    try:
        fetcher = GmailFetcher(access_token=token)
        extracted = fetcher.fetch_and_extract_email(email_id)
        
        return extract_email_to_response(extracted)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/applications/save/{email_id}", response_model=SaveResult)
async def save_application(
    email_id: str,
    token: str = Depends(verify_google_token)
):
    """
    Process an email and save the job application to Supabase.
    
    This endpoint:
        1. Fetches the email from Gmail
        2. Uses the LLM to classify and extract information
        3. Saves to Supabase if it's a job application
    
    Args:
        email_id: The Gmail message ID to process
        token: Validated Google access token (injected by dependency)
        
    Returns:
        SaveResult indicating success or failure
    """
    try:
        # Fetch the email
        fetcher = GmailFetcher(access_token=token)
        extracted = fetcher.fetch_and_extract_email(email_id)
        
        # Save to debug file (only in development)
        save_email_for_debugging(extracted)
        
        # Save to database using singleton tracker (uses LLM extraction internally)
        success = job_tracker.save_application(extracted)
        
        if success:
            return SaveResult(
                success=True,
                message="Application saved successfully"
            )
        else:
            return SaveResult(
                success=False,
                message="Application already exists or email is not a job application"
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/applications", response_model=list[dict])
async def get_applications():
    """
    Get all saved job applications from the database.
    
    This endpoint does not require authentication since viewing
    applications is not sensitive.
    
    Returns:
        List of application records from Supabase
    """
    try:
        # Use singleton tracker instead of creating new instance
        applications = job_tracker.get_all_applications()
        return applications
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/applications/process-latest", response_model=SaveResult)
async def process_latest_email(
    query: str = "in:inbox",
    token: str = Depends(verify_google_token)
):
    """
    Fetch the latest email matching query and save as application.
    
    This is a convenience endpoint for quickly processing the most
    recent email without needing to fetch the email list first.
    
    Args:
        query: Gmail search query to find the email
        token: Validated Google access token (injected by dependency)
        
    Returns:
        SaveResult indicating success or failure
    """
    try:
        fetcher = GmailFetcher(access_token=token)
        extracted, _ = fetcher.fetch_latest_email_for_llm(query=query)
        
        # Save to debug file (only in development)
        save_email_for_debugging(extracted)
        
        # Process and save using singleton tracker
        success = job_tracker.save_application(extracted)
        
        return SaveResult(
            success=success,
            message="Processed latest email" if success else "Already tracked or not a job application"
        )
        
    except ValueError as e:
        # No emails found matching query
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# RUN SERVER
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 50)
    print("  SyncApply API Server")
    print("=" * 50)
    print()
    print(f"Environment: {'Production' if IS_PRODUCTION else 'Development'}")
    print("Starting server...")
    print("API docs available at: http://localhost:8000/docs")
    print()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
