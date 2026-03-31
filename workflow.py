import os
import json
import re
import operator
from typing import List, TypedDict, Annotated

# --- LangChain/LangGraph Imports ---
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END


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


# --- 2. Node: The Optimizer (Improved Prompt) ---
def query_optimizer(state: AgentState):
    """Generates a refined web search query."""
    print(f"--- OPTIMIZING QUERY (Iter {state['iterations']}) ---")

    ### IMPROVEMENT 1: More dynamic prompt to avoid getting stuck ###
    prompt = f"""You are an expert at crafting precise job search queries.
    
    User Goal: {state['specifications']}
    Feedback from last search: {state.get('critique', 'None')}
    
    INSTRUCTIONS:
    - Based on the feedback, create a new, effective search query.
    - If the feedback suggests the last query was bad, try a completely different structure or keywords.
    - Use 'site:linkedin.com/jobs/view' OR 'site:indeed.com/viewjob'.
    - Return ONLY the generated search query as a single line of text. No preamble or explanations.
    """

    response_content = llm.invoke(prompt).content
    lines = response_content.strip().split("\n")
    refined_query = lines[-1].strip().replace('"', "").replace("`", "")
    return {"current_search_query": refined_query}


# --- 3. Node: Search & Parse (New Robust Approach) ---
### IMPROVEMENT 2: Use the LLM to parse the messy tool output ###
def search_and_parse_node(state: AgentState):
    """
    Searches the web and uses an LLM to reliably parse the results,
    even if the tool's output is not perfect JSON.
    """
    query = state["current_search_query"]
    print(f"--- SEARCHING & PARSING: {query} ---")

    raw_results_str = search_tool.invoke(query)

    if not raw_results_str:
        print("   WARN: Search tool returned no results at all.")
        return {"job_listings": []}

    # Now, use the LLM to convert the messy string into clean JSON
    parsing_prompt = f"""
    You are a data extraction expert. A search tool returned the following text blob.
    Your task is to extract job listings and format them into a clean JSON object containing a single key "jobs", which is a list of dictionaries.
    Each dictionary must have the keys "title", "url", and "snippet".
    
    - The 'url' must be a valid, complete URL.
    - If a job has no snippet, use "No snippet available.".
    - Ignore any ads, non-job links, or malformed entries.
    
    TEXT BLOB TO PARSE:
    {raw_results_str}
    
    Return ONLY the JSON object.
    """

    try:
        # We use the json_llm to ensure the output is structured
        response = json_llm.invoke(parsing_prompt)

        # The content from json_llm can be a string or already a dict
        if isinstance(response.content, str):
            parsed_data = json.loads(response.content)
        else:
            parsed_data = response.content

        job_list = parsed_data.get("jobs", [])

        print(f"   Successfully parsed {len(job_list)} jobs from search results.")
        return {"job_listings": job_list}

    except (json.JSONDecodeError, AttributeError) as e:
        print(f"   ERROR: LLM failed to parse the search results. Error: {e}")
        return {"job_listings": []}


# --- 4. Node: Batch Validator (Improved Prompt) ---
def batch_validator(state: AgentState):
    """Uses the LLM to validate a batch of search results."""
    print(f"--- BATCH VALIDATING {len(state['job_listings'])} JOBS ---")

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
    
    JOBS LIST:
    {jobs_formatted}
    
    INSTRUCTIONS:
    1.  **Analyze Step-by-Step**: For each job ID, first internally decide if it meets the criteria. A good match should explicitly mention "Junior", "Entry-Level", or similar terms and be in the correct location (Berlin/Remote). Be pragmatic; a "Software Engineer" role in a junior-focused company might be acceptable if the snippet suggests it.
    2.  **Filter Strictly**: Reject any jobs that are obviously "Senior", "Lead", "Principal", or require many years of experience. Also reject aggregate list pages or ads.
    3.  **Provide Feedback**: After analyzing all jobs, formulate a single, constructive feedback sentence to improve the *next* search. For example, "The search returned too many senior roles, so the next query should be more specific about entry-level positions." or "Results were good, continue with this focus."
    4.  **Format Output**: You MUST return a single, valid JSON object with two keys:
        - "passed_ids": A list of integer IDs for the jobs that passed validation. If no jobs pass, return an empty list [].
        - "feedback": A string containing your feedback.
    
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

        print(f"   Batch complete: {len(final_selections)} jobs passed validation.")
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
    if state["iterations"] >= 4 or len(state["valid_results"]) >= 5:
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

# --- Run the graph ---
inputs = {
    "specifications": "Junior AI Engineer or Junior Machine Learning Engineer roles in Berlin. Must be entry-level. Can be remote, but should be a european company. Avoid senior/lead positions. Only job postings that are valid (30 days old max), not articles or lists.",
    "job_listings": [],
    "valid_results": [],
    "critique": "None",
    "iterations": 0,
}

final_output = app.invoke(inputs)

print("\n" + "🚀" * 15)
print(
    f"FOUND {len(final_output['valid_results'])} VALID JOBS AFTER {final_output['iterations']} ITERATIONS"
)
print("🚀" * 15)
for job in final_output["valid_results"]:
    print(f"- Title: {job['title']}\n  URL: {job['url']}\n")
