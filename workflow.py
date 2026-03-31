import time
import random
import re
from ddgs.exceptions import DDGSException
import json
import operator
from typing import List, TypedDict, Annotated
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END
from pdf2image import convert_from_path
import pytesseract

# On Windows, you need to point pytesseract to your Tesseract installation:
# pip install pytesseract pdf2image
# Also install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
pytesseract.pytesseract.tesseract_cmd = r"E:/Tesseract/tesseract.exe"


def create_prompt_from_resume(file_path: str, job_location: str) -> str:
    # 1. Convert each PDF page to an image, then OCR it
    resume_text = ""
    try:
        # poppler_path is required on Windows — install via:
        # https://github.com/oschwartz10612/poppler-windows/releases
        # then set the path below:
        pages = convert_from_path(
            file_path,
            dpi=300,  # Higher DPI = better OCR accuracy
            poppler_path=r"E:/Poppler/poppler-25.12.0/Library/bin",  # ← adjust to your install path
        )

        for i, page_image in enumerate(pages):
            page_text = pytesseract.image_to_string(page_image, lang="eng")
            resume_text += page_text + "\n"

    except Exception as e:
        print(f"   ERROR during OCR: {e}")
        return "Junior AI Engineer or Junior Machine Learning Engineer roles in Berlin or Remote."

    # 2. Guard: confirm we got meaningful content
    resume_text = resume_text.strip()
    if not resume_text or len(resume_text) < 100:
        print(f"   ERROR: OCR extracted too little text ({len(resume_text)} chars).")
        return "Junior AI Engineer or Junior Machine Learning Engineer roles in Berlin or Remote."

    print(f"   ✅ OCR extracted {len(resume_text)} characters from resume.")

    # 3. Prompt the LLM — cap at 4000 chars to stay within llama3.1's context
    prompt_to_llm = f"""You are a professional career coach and expert prompt engineer.

Analyze the resume below and generate a concise, one-sentence job specification prompt for a job-finding agent. The found jobs should ideally involve some level of AI or machine learning.

The prompt must:
1. Identify the candidate's apparent experience level.
2. Extract 2-3 of the most prominent and modern skills or technologies.
3. Incorporate the desired job location: "{job_location}".
4. Combine into a single, effective search specification.

RESUME TEXT:
---
{resume_text[:4000]}
---

Output only the one-sentence specification. No preamble, no quotes."""

    generated_spec = llm.invoke(prompt_to_llm).content.strip().replace('"', "")
    return generated_spec


# --- 1. Refined State (Unchanged) ---
class AgentState(TypedDict):
    specifications: str
    current_search_query: str
    job_listings: List[dict]
    valid_results: Annotated[List[dict], operator.add]
    critique: str
    iterations: int


# Instantiate the local Ollama LLM
llm = ChatOllama(model="llama3.1", temperature=0)
# This will be used specifically for forcing JSON outputs
json_llm = llm.bind(format="json")

# Instantiate the search tool
search_tool = DuckDuckGoSearchResults(
    max_results=10
)  # Reduced to 10 for faster iteration


# --- Query Sanitizer Helper ---
def sanitize_query(query: str) -> str:
    """
    Strips syntax that breaks DuckDuckGo's API:
    complex boolean operators, site: filters, parentheses, slashes.
    Keeps it short and clean.
    """
    # Remove site: operators entirely
    query = re.sub(r"site:\S+", "", query)
    # Remove boolean operators
    query = re.sub(r"\b(AND|OR|NOT)\b", "", query)
    # Remove parentheses, backticks, quotes
    query = re.sub(r'[()"`]', "", query)
    # Collapse extra whitespace
    query = re.sub(r"\s+", " ", query).strip()
    # DDG works best with short queries — cap at 20 words
    words = query.split()
    if len(words) > 20:
        query = " ".join(words[:20])
    return query


# --- 2. Node: Query Optimizer (unchanged logic, same as before) ---
def query_optimizer(state: AgentState):
    """Generates a refined web search query."""
    prompt = f"""You are an expert at crafting precise job search queries for DuckDuckGo.
    
    User Goal: {state['specifications']}
    Feedback from last search: {state.get('critique', 'None')}
    
    INSTRUCTIONS:
    - Write a short, simple search query of 6-8 words maximum.
    - Do NOT use boolean operators (AND, OR, NOT), parentheses, or site: filters.
    - Focus on the job title, key skills, and location.
    - Return ONLY the query as a single line. No preamble.
    """

    response_content = llm.invoke(prompt).content
    lines = response_content.strip().split("\n")
    raw_query = lines[-1].strip().replace('"', "").replace("`", "")
    # Sanitize as a safety net even if the LLM follows instructions
    refined_query = sanitize_query(raw_query)
    print(f"   Query: '{refined_query}'")
    return {"current_search_query": refined_query}


# --- 3. Node: Search & Parse (with retry + backoff) ---
def search_and_parse_node(state: AgentState):
    """
    Searches the web with retry/backoff and uses an LLM to parse results.
    """
    query = state["current_search_query"]

    # Retry up to 3 times with exponential backoff
    raw_results_str = None
    for attempt in range(3):
        try:
            raw_results_str = search_tool.invoke(query)
            break  # Success — exit retry loop
        except DDGSException as e:
            wait = (2**attempt) + random.uniform(0, 1)  # 1s, 2s, 4s + jitter
            print(f"   WARN: DDG search failed (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                print(f"   Retrying in {wait:.1f}s...")
                time.sleep(wait)
            else:
                print("   ERROR: All retries exhausted. Skipping this search.")
                return {"job_listings": []}

    if not raw_results_str:
        print("   WARN: Search returned no results.")
        return {"job_listings": []}

    # Use the LLM to parse the raw results into structured JSON
    parsing_prompt = f"""
    You are a data extraction expert. A search tool returned the following text blob.
    Extract job listings and format them into a JSON object with a single key "jobs" — a list of dicts.
    Each dict must have: "title", "url", "snippet".
    - 'url' must be a valid complete URL.
    - If no snippet exists, use "No snippet available."
    - Ignore ads, non-job links, and malformed entries.
    
    TEXT BLOB:
    {raw_results_str}
    
    Return ONLY the JSON object.
    """

    try:
        response = json_llm.invoke(parsing_prompt)
        parsed_data = (
            json.loads(response.content)
            if isinstance(response.content, str)
            else response.content
        )
        job_list = parsed_data.get("jobs", [])
        return {"job_listings": job_list}

    except (json.JSONDecodeError, AttributeError) as e:
        print(f"   ERROR: LLM failed to parse search results: {e}")
        return {"job_listings": []}


# --- 4. Node: Batch Validator (Improved Prompt) ---
def batch_validator(state: AgentState):
    """Uses the LLM to validate a batch of search results."""

    if not state["job_listings"]:
        return {
            "critique": "The search and parsing step found no valid jobs. The search query might be too narrow or the web results were irrelevant. Try a different query.",
            "iterations": state["iterations"] + 1,
        }

    jobs_formatted = ""
    for i, job in enumerate(state["job_listings"]):
        jobs_formatted += f"ID: {i}\nTitle: {job['title']}\nURL: {job['url']}\nSnippet: {job['snippet']}\n---\n"

    ### IMPROVEMENT 3: A more detailed and robust validation prompt ###
    prompt = f"""You are a strict but fair job filtering assistant. Your task is to analyze a list of job postings and determine if they match the user's criteria.

    USER CRITERIA:
    {state['specifications']}
    
    INITIAL SPECIFICATIONS:
    {initial_specifications}
    
    
    JOBS LIST:
    {jobs_formatted}
    
    INSTRUCTIONS:
    1.  **Analyze Step-by-Step**: For each job ID, first internally decide if it meets the criteria. A good match should explicitly mention "Junior", "Entry-Level", or similar terms and be in the correct location (Berlin/Remote). Be pragmatic; a "Software Engineer" role in a junior-focused company might be acceptable if the snippet suggests it.
    2.  **Filter Strictly**: Reject any jobs that are obviously "Senior", "Lead", "Principal", or require many years of experience. Also reject aggregate list pages or ads.
    3.  **Provide Feedback**: After analyzing all jobs, formulate a single, constructive feedback sentence to improve the *next* search. For example, "The search returned too many senior roles, so the next query should be more specific about entry-level positions." or "Results were good, continue with this focus."
    4.  **Format Output**: You MUST return a single, valid JSON object with two keys:
        - "passed_ids": A list of integer IDs for the jobs that passed validation. If no jobs pass, return an empty list [].
        - "feedback": A string containing your feedback.
    5.  **URL Validation**: The provided link should link to a singular specific job offer, not a list of jobs or an ad. If the URL is not a direct job listing, reject it.
    
    Do not include any other text or explanations outside of the JSON object.
    """

    try:
        response = json_llm.invoke(prompt)
        result_data = (
            json.loads(response.content)
            if isinstance(response.content, str)
            else response.content
        )

        passed_ids = result_data.get("passed_ids", [])
        feedback = result_data.get(
            "feedback",
            "General check failed. Be more specific about seniority and location.",
        )

        final_selections = [
            state["job_listings"][idx]
            for idx in passed_ids
            if isinstance(idx, int) and idx < len(state["job_listings"])
        ]

        print(f"Validation feedback: {feedback}")

        return {
            "valid_results": final_selections,
            "critique": feedback,
            "iterations": state["iterations"] + 1,
            "job_listings": [],
        }
    except Exception as e:
        print(f"   ERROR during validation LLM call: {e}")
        return {
            "critique": "Model failed to return valid JSON for validation. Let's try a simpler query.",
            "iterations": state["iterations"] + 1,
        }


# --- 5. Graph Assembly ---
def should_continue(state: AgentState):
    ### IMPROVEMENT 4: Tweak the stopping condition for better results ###
    if len(state["valid_results"]) >= 5:
        print("--- CONDITION MET: ENDING WORKFLOW ---")
        return "end"
    print("--- CONDITION NOT MET: CONTINUING WORKFLOW ---")
    return "continue"


workflow = StateGraph(AgentState)

workflow.add_node("optimizer", query_optimizer)
# The searcher node is now the new search_and_parse_node
workflow.add_node("searcher", search_and_parse_node)
workflow.add_node("validator", batch_validator)

workflow.set_entry_point("optimizer")
workflow.add_edge("optimizer", "searcher")
workflow.add_edge("searcher", "validator")

workflow.add_conditional_edges(
    "validator", should_continue, {"continue": "optimizer", "end": END}
)

app = workflow.compile()

# 1. Define the path to your resume and desired location
resume_file_path = "C:\\Users\\lherm\\Downloads\\LeonHermannResume_clean.pdf"  # IMPORTANT: Change this to the correct path!
desired_location = "Berlin or Potsdam"

# 2. Call the new agent to create the prompt
initial_specifications = create_prompt_from_resume(
    file_path=resume_file_path, job_location=desired_location
)

print(f"✅ PERSONALIZED SPECIFICATIONS CREATED:\n   '{initial_specifications}'")


# 3. Run the graph with the *generated* specifications
inputs = {
    "specifications": initial_specifications,
    "job_listings": [],
    "valid_results": [],
    "critique": "None",
    "iterations": 0,
}

final_output = app.invoke(inputs)

print(
    f"FOUND {len(final_output['valid_results'])} VALID JOBS AFTER {final_output['iterations']} ITERATIONS"
)
for job in final_output["valid_results"]:
    print(f"- Title: {job['title']}\n  URL: {job['url']}\n")
