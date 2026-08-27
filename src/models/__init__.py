"""Data Schemas & Pydantic Data Structures package.

Description: Contains Pydantic models shared across agents and MCP servers.
Need: Agents exchange structured payloads (checkpoints, cost objects,
      security reports); without shared schemas, contracts drift silently.
Motive: Provide a single validated schema definition per data shape used
        throughout the pipeline.
"""
