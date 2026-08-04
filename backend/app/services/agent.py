import os
import json
import uuid
import logging
from typing import AsyncGenerator, Dict, Any, Optional, List
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app import crud, models
from app.config import settings
from app.services.demand import DemandSurgeDetector

logger = logging.getLogger("agent")

# Optional: Add your OpenAI API Key directly to environment or .env
api_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
client = AsyncOpenAI(api_key=api_key)

class AnchorpointAgent:
    def __init__(self, db: AsyncSession, run_id: str):
        self.db = db
        self.run_id = uuid.UUID(run_id)

    async def get_region_summary(self) -> str:
        regions = await crud.get_run_regions(self.db, self.run_id)
        if not regions:
            return "No regions found for this run."
        
        summary = f"Found {len(regions)} regions for this run:\n"
        for r in regions:
            summary += f"- Region {r.id}: {r.name} (Centroid: {r.centroid_lat}, {r.centroid_lng}, Radius: {r.radius_km} km)\n"
        return summary
        
    async def get_site_scores(self, region_id_str: str) -> str:
        try:
            region_id = uuid.UUID(region_id_str)
            sites = await crud.get_region_sites(self.db, region_id)
            if not sites:
                return "No sites found for this region."
                
            summary = "Site scores:\n"
            for s in sites:
                score = s.scores[0] if s.scores else None
                if score and score.composite_score is not None:
                    summary += f"- Site '{s.name}': Composite Score = {score.composite_score:.2f} (Completeness: {score.data_completeness_pct:.0f}%)\n"
                else:
                    summary += f"- Site '{s.name}': Not yet scored or insufficient data.\n"
            return summary
        except Exception as e:
            return f"Error retrieving site scores: {str(e)}"

    async def get_surge_analysis(self) -> str:
        run = await crud.get_run(self.db, self.run_id)
        if not run:
            return "Run not found."
            
        current_points = await crud.get_run_demand_points(self.db, self.run_id)
        current_dicts = [{"lat": p.lat, "lng": p.lng, "zip_code": p.zip_code, "order_count": p.order_count, "weight": p.weight} for p in current_points]
        
        previous_runs = await self.db.execute(
            select(models.Run)
            .where(models.Run.created_at < run.created_at)
            .order_by(models.Run.created_at.desc())
            .limit(1)
        )
        prev_run = previous_runs.scalar_one_or_none()
        
        if not prev_run:
            skew = DemandSurgeDetector.estimate_internal_surge_score(current_dicts)
            return f"No previous runs to compare against. Internal demand skew score is {skew:.2f} (0 is even, 1 is highly skewed)."
            
        prev_points = await crud.get_run_demand_points(self.db, prev_run.id)
        prev_dicts = [{"lat": p.lat, "lng": p.lng, "zip_code": p.zip_code, "order_count": p.order_count, "weight": p.weight} for p in prev_points]
        
        surging_zips = DemandSurgeDetector.compare_demand_snapshots(prev_dicts, current_dicts)
        if not surging_zips:
            return "Compared to the previous run, no significant demand surges were detected."
            
        result = f"Found {len(surging_zips)} surging ZIP codes compared to previous run:\n"
        for sz in surging_zips:
            result += f"- ZIP {sz['zip_code']}: Grew {sz['growth_factor']:.1f}x (from {sz['old_weight']} to {sz['new_weight']} orders)\n"
        return result

    async def run_pipeline(self, user_message: str, history: Optional[List[Dict[str, str]]] = None) -> AsyncGenerator[str, None]:
        current_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
        if not current_key:
            yield json.dumps({"type": "answer", "content": "Error: OPENAI_API_KEY environment variable is not set. Please configure it in .env to use the Agentic Pipeline."})
            return

        yield json.dumps({"type": "thinking", "content": "Analyzing request..."})

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_region_summary",
                    "description": "Gets a list of all candidate regions/hubs for the current siting run."
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_site_scores",
                    "description": "Gets all candidate sites and their Mireye suitability scores for a specific region.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "region_id": {"type": "string", "description": "The UUID of the region"}
                        },
                        "required": ["region_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_surge_analysis",
                    "description": "Analyses demand surges by comparing current run data to historical runs."
                }
            }
        ]

        system_instruction = (
            "You are a logistics network AI assistant for Anchorpoint (powered by Mireye Earth data).\n"
            "Your job is to answer questions about candidate regions, site rankings, Mireye scores, and demand surges.\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. ALWAYS call tools to retrieve data before making assertions. If you need to know about sites in a region, call `get_region_summary` first to get region IDs, then immediately call `get_site_scores` for that region.\n"
            "2. NEVER output placeholder phrases like 'Please wait while I retrieve...' or 'I am gathering data...'. Execute tool calls silently and provide the final answer directly.\n"
            "3. Be concise, quantitative, and professional."
        )

        messages = [{"role": "system", "content": system_instruction}]
        
        # Include past chat history if provided
        if history:
            for h in history:
                if h.get("role") in ("user", "assistant") and h.get("content"):
                    messages.append({"role": h["role"], "content": h["content"]})
                    
        messages.append({"role": "user", "content": user_message})

        try:
            # Allow up to 3 turns of tool calling
            for turn in range(3):
                response = await client.chat.completions.create(
                    model=settings.AGENT_MODEL,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
                
                message = response.choices[0].message
                
                if message.tool_calls:
                    messages.append(message.model_dump())
                    
                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        try:
                            arguments = json.loads(tool_call.function.arguments or "{}")
                        except Exception:
                            arguments = {}
                            
                        yield json.dumps({"type": "tool_call", "tool_name": function_name, "args": arguments})
                        
                        tool_result = ""
                        if function_name == "get_region_summary":
                            tool_result = await self.get_region_summary()
                        elif function_name == "get_site_scores":
                            tool_result = await self.get_site_scores(arguments.get("region_id", ""))
                        elif function_name == "get_surge_analysis":
                            tool_result = await self.get_surge_analysis()
                        else:
                            tool_result = f"Unknown function: {function_name}"
                            
                        yield json.dumps({"type": "tool_result", "tool_name": function_name, "result": tool_result})
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": function_name,
                            "content": tool_result,
                        })
                else:
                    # No tool calls requested — this is the final text response!
                    yield json.dumps({"type": "answer", "content": message.content})
                    return

            # If we completed max turns of tool calls, stream the final answer
            yield json.dumps({"type": "thinking", "content": "Synthesising final answer..."})
            
            final_response = await client.chat.completions.create(
                model=settings.AGENT_MODEL,
                messages=messages,
                stream=True,
            )
            
            async for chunk in final_response:
                if chunk.choices[0].delta.content:
                    yield json.dumps({"type": "answer_chunk", "content": chunk.choices[0].delta.content})

        except Exception as e:
            logger.error(f"Agent error: {e}")
            yield json.dumps({"type": "answer", "content": f"An error occurred while running the agent: {str(e)}"})
