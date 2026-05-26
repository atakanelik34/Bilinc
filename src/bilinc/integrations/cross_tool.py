"""
Cross-Tool Memory Translation Layer

Translates memory between different agent tools/frameworks:
- OpenClaw ↔ Cursor ↔ Claude Code ↔ VS Code ↔ Custom Agents
- Each tool has its own memory format (CLAUDE.md, Cursor memory, etc.)
- This layer provides universal translation via the Bilinc StatePlane

Architecture:
1. Source Format Parser (Claude → Bilinc)
2. StatePlane Storage (unified representation)
3. Target Format Generator (Bilinc → Cursor, etc.)

Supports:
- Claude Code: CLAUDE.md + auto memory format
- Cursor: .cursor/settings.json + memory bank
- VS Code: .vscode/settings.json
- OpenClaw: AGENTS.md + harness state
- MCP: Universal JSON format
"""
from __future__ import annotations
import json
import os
import re
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from bilinc.core.stateplane import StatePlane
from bilinc.core.models import MemoryEntry, MemoryType

logger = logging.getLogger(__name__)


class ToolFormat(str, Enum):
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    VS_CODE = "vs_code"
    OPENCLAW = "openclaw"
    MCP = "mcp"
    GENERIC = "generic"


@dataclass
class ToolMemoryBlock:
    """A parsed memory block from a specific tool's format."""
    tool: ToolFormat
    content: str
    metadata: Dict[str, Any]
    memory_type: MemoryType
    source_path: str = ""


class CrossToolTranslator:
    """
    Translates memory between agent tools via StatePlane.
    
    Usage:
        translator = CrossToolTranslator(state_plane)
        # Import from Claude Code
        translator.import_from_tool("/path/to/CLAUDE.md", ToolFormat.CLAUDE_CODE)
        # Export to Cursor
        translator.export_to_tool("/path/to/.cursor/memory.json", ToolFormat.CURSOR)
        # Or use StatePlane directly for universal access
    """
    
    def __init__(self, state_plane: Optional[StatePlane] = None):
        self.state_plane = state_plane or StatePlane()
    
    # ─── Import: Tool → StatePlane ─────────────────────────────
    
    def import_from_tool(
        self,
        path: str,
        tool_format: ToolFormat,
        session_id: str = "",
        verify: bool = True,
    ) -> List[str]:
        """
        Import memory from a tool-specific format into StatePlane.
        
        Returns list of committed memory keys.
        """
        if not os.path.exists(path):
            logger.warning(f"Path does not exist: {path}")
            return []
        
        with open(path, "r") as f:
            content = f.read()
        
        blocks = self._parse_tool_format(content, tool_format, path)
        committed_keys = []
        
        for block in blocks:
            try:
                # Sanitize path for key (replace slashes with underscores)
                safe_path = block.source_path.replace("/", "_").replace("\\", "_")
                result = self.state_plane.commit_sync(
                    key=f"{tool_format.value}:{safe_path}:{hash(block.content) % 10000}",
                    value=block.content,
                    memory_type=block.memory_type,
                    verify=verify,
                    metadata=block.metadata,
                )
                # commit_sync returns MemoryEntry or coroutine result
                if hasattr(result, 'key'):
                    committed_keys.append(result.key)
                elif isinstance(result, dict) and 'key' in result:
                    committed_keys.append(result['key'])
                else:
                    committed_keys.append(f"unknown_{len(committed_keys)}")
            except Exception as e:
                logger.warning(f"Failed to commit block: {e}")
                committed_keys.append(f"failed_{len(committed_keys)}")
        
        logger.info(f"Imported {len(committed_keys)} blocks from {tool_format.value}: {path}")
        return committed_keys
    
    def _parse_tool_format(
        self, content: str, tool: ToolFormat, source_path: str
    ) -> List[ToolMemoryBlock]:
        """Parse tool-specific memory format into ToolMemoryBlocks."""
        parsers = {
            ToolFormat.CLAUDE_CODE: self._parse_claude_code,
            ToolFormat.CURSOR: self._parse_cursor,
            ToolFormat.VS_CODE: self._parse_vs_code,
            ToolFormat.OPENCLAW: self._parse_openclaw,
            ToolFormat.MCP: self._parse_mcp,
            ToolFormat.GENERIC: self._parse_generic,
        }
        parser = parsers.get(tool, self._parse_generic)
        return parser(content, source_path)
    
    def _parse_claude_code(self, content: str, source_path: str) -> List[ToolMemoryBlock]:
        """Parse CLAUDE.md and Claude auto memory format."""
        blocks = []
        
        # CLAUDE.md: structured sections
        section_pattern = r'#+\s+(.+?)\n([\s\S]*?)(?=^#+\s+|\Z)'
        for match in re.finditer(section_pattern, content, re.MULTILINE):
            title = match.group(1).strip()
            body = match.group(2).strip()
            
            mem_type = self._classify_claude_section(title)
            blocks.append(ToolMemoryBlock(
                tool=ToolFormat.CLAUDE_CODE,
                content=body,
                metadata={"section": title, "format": "claude.md"},
                memory_type=mem_type,
                source_path=source_path,
            ))
        
        if not blocks and content.strip():
            blocks.append(ToolMemoryBlock(
                tool=ToolFormat.CLAUDE_CODE,
                content=content,
                metadata={"format": "claude.md"},
                memory_type=MemoryType.SEMANTIC,
                source_path=source_path,
            ))
        
        return blocks
    
    def _parse_cursor(self, content: str, source_path: str) -> List[ToolMemoryBlock]:
        """Parse Cursor memory/settings format."""
        blocks = []
        try:
            data = json.loads(content)
            for key, value in data.items():
                blocks.append(ToolMemoryBlock(
                    tool=ToolFormat.CURSOR,
                    content=json.dumps(value) if isinstance(value, (dict, list)) else str(value),
                    metadata={"key": key, "format": "cursor"},
                    memory_type=MemoryType.SEMANTIC,
                    source_path=source_path,
                ))
        except json.JSONDecodeError:
            # Plain text format
            blocks.append(ToolMemoryBlock(
                tool=ToolFormat.CURSOR,
                content=content,
                metadata={"format": "cursor"},
                memory_type=MemoryType.SEMANTIC,
                source_path=source_path,
            ))
        return blocks
    
    def _parse_vs_code(self, content: str, source_path: str) -> List[ToolMemoryBlock]:
        """Parse VS Code settings/memory format."""
        blocks = []
        try:
            data = json.loads(content)
            blocks.append(ToolMemoryBlock(
                tool=ToolFormat.VS_CODE,
                content=json.dumps(data, indent=2),
                metadata={"format": "vscode", "settings_count": len(data)},
                memory_type=MemoryType.SEMANTIC,
                source_path=source_path,
            ))
        except json.JSONDecodeError:
            blocks.append(ToolMemoryBlock(
                tool=ToolFormat.VS_CODE,
                content=content,
                metadata={"format": "vscode"},
                memory_type=MemoryType.SEMANTIC,
                source_path=source_path,
            ))
        return blocks
    
    def _parse_openclaw(self, content: str, source_path: str) -> List[ToolMemoryBlock]:
        """Parse OpenClaw AGENTS.md format."""
        blocks = []
        # AGENTS.md typically has sections like: ## Rules, ## Context, ## Examples
        section_pattern = r'##\s+(.+?)\n([\s\S]*?)(?=^##\s+|\Z)'
        for match in re.finditer(section_pattern, content, re.MULTILINE):
            title = match.group(1).strip()
            body = match.group(2).strip()
            mem_type = self._classify_openclaw_section(title)
            blocks.append(ToolMemoryBlock(
                tool=ToolFormat.OPENCLAW,
                content=body,
                metadata={"section": title, "format": "agents.md"},
                memory_type=mem_type,
                source_path=source_path,
            ))
        
        if not blocks and content.strip():
            blocks.append(ToolMemoryBlock(
                tool=ToolFormat.OPENCLAW,
                content=content,
                metadata={"format": "agents.md"},
                memory_type=MemoryType.SEMANTIC,
                source_path=source_path,
            ))
        
        return blocks
    
    def _parse_mcp(self, content: str, source_path: str) -> List[ToolMemoryBlock]:
        """Parse MCP universal JSON format."""
        blocks = []
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    blocks.append(ToolMemoryBlock(
                        tool=ToolFormat.MCP,
                        content=json.dumps(item),
                        metadata={"format": "mcp"},
                        memory_type=MemoryType(item.get("type", "episodic")),
                        source_path=source_path,
                    ))
            elif isinstance(data, dict):
                blocks.append(ToolMemoryBlock(
                    tool=ToolFormat.MCP,
                    content=json.dumps(data),
                    metadata={"format": "mcp"},
                    memory_type=MemoryType(data.get("type", "episodic")),
                    source_path=source_path,
                ))
        except json.JSONDecodeError:
            blocks.append(ToolMemoryBlock(
                tool=ToolFormat.MCP,
                content=content,
                metadata={"format": "mcp"},
                memory_type=MemoryType.EPISODIC,
                source_path=source_path,
            ))
        return blocks
    
    def _parse_generic(self, content: str, source_path: str) -> List[ToolMemoryBlock]:
        """Parse generic text as a single memory block."""
        return [ToolMemoryBlock(
            tool=ToolFormat.GENERIC,
            content=content,
            metadata={"format": "generic"},
            memory_type=MemoryType.SEMANTIC,
            source_path=source_path,
        )]
    
    def _classify_claude_section(self, title: str) -> MemoryType:
        """Classify CLAUDE.md section into memory type."""
        title_lower = title.lower()
        if any(k in title_lower for k in ["rule", "constraint", "policy", "format", "style"]):
            return MemoryType.SEMANTIC
        if any(k in title_lower for k in ["example", "instruction", "process", "workflow", "step"]):
            return MemoryType.PROCEDURAL
        if any(k in title_lower for k in ["context", "decision", "note", "history", "session"]):
            return MemoryType.EPISODIC
        return MemoryType.SEMANTIC
    
    def _classify_openclaw_section(self, title: str) -> MemoryType:
        """Classify AGENTS.md section into memory type."""
        title_lower = title.lower()
        if any(k in title_lower for k in ["rule", "constraint", "guideline", "policy"]):
            return MemoryType.SEMANTIC
        if any(k in title_lower for k in ["process", "workflow", "step", "how", "instruction"]):
            return MemoryType.PROCEDURAL
        if any(k in title_lower for k in ["example", "history", "session", "note", "context"]):
            return MemoryType.EPISODIC
        return MemoryType.SEMANTIC
    
    # ─── Export: StatePlane → Tool ─────────────────────────────
    
    def export_to_tool(
        self,
        path: str,
        tool_format: ToolFormat,
        memory_types: Optional[List[MemoryType]] = None,
        budget_tokens: int = 4096,
        overwrite: bool = False,
    ) -> str:
        """
        Export memories from StatePlane to a tool-specific format.
        
        Returns the generated content (also written to path if specified).
        """
        # Use sync recall from working memory for export
        if hasattr(self.state_plane, 'recall_all_sync'):
            memories = self.state_plane.recall_all_sync()
        elif hasattr(self.state_plane, 'working_memory'):
            memories = self.state_plane.working_memory.get_all()
        else:
            memories = []
        
        exporters = {
            ToolFormat.CLAUDE_CODE: self._export_to_claude_code,
            ToolFormat.CURSOR: self._export_to_cursor,
            ToolFormat.VS_CODE: self._export_to_vs_code,
            ToolFormat.OPENCLAW: self._export_to_openclaw,
            ToolFormat.MCP: self._export_to_mcp,
            ToolFormat.GENERIC: self._export_to_generic,
        }
        exporter = exporters.get(tool_format, self._export_to_generic)
        output = exporter(memories)
        
        if path and overwrite:
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, "w") as f:
                f.write(output)
            logger.info(f"Exported {len(memories)} memories to {path}")
        
        return output
    
    def _export_to_claude_code(self, memories: List[MemoryEntry]) -> str:
        """Export to CLAUDE.md format."""
        sections: Dict[str, List[MemoryEntry]] = {
            "Rules & Constraints": [],
            "Procedures & Workflows": [],
            "Context & Notes": [],
            "Knowledge": [],
        }
        
        for m in memories:
            if m.memory_type == MemoryType.SEMANTIC:
                sections["Rules & Constraints"].append(m)
            elif m.memory_type == MemoryType.PROCEDURAL:
                sections["Procedures & Workflows"].append(m)
            elif m.memory_type == MemoryType.EPISODIC:
                sections["Context & Notes"].append(m)
            else:
                sections["Knowledge"].append(m)
        
        output = "# CLAUDE.md (Generated by Bilinc)\n"
        output += f"# Last updated: {memories[0].updated_at if memories else ''}\n\n"
        
        for section, mems in sections.items():
            if mems:
                output += f"## {section}\n\n"
                for m in mems:
                    value = m.value if isinstance(m.value, str) else json.dumps(m.value)
                    output += f"### {m.key}\n{value}\n\n"
                output += "\n"
        
        return output
    
    def _export_to_cursor(self, memories: List[MemoryEntry]) -> str:
        """Export to Cursor memory/settings JSON format."""
        data = {}
        for m in memories:
            key = m.key
            data[key] = m.value
        return json.dumps(data, indent=2)
    
    def _export_to_vs_code(self, memories: List[MemoryEntry]) -> str:
        """Export to VS Code settings JSON format."""
        settings = {}
        for m in memories:
            # Prefix with synaptic to avoid conflicts
            settings[f"synaptic.{m.key}"] = m.value
            if m.metadata:
                settings[f"synaptic.meta.{m.key}"] = m.metadata
        return json.dumps(settings, indent=2)
    
    def _export_to_openclaw(self, memories: List[MemoryEntry]) -> str:
        """Export to AGENTS.md format."""
        sections: Dict[str, List[MemoryEntry]] = {
            "Rules": [],
            "Workflows": [],
            "Notes": [],
            "Knowledge": [],
        }
        
        for m in memories:
            if m.memory_type == MemoryType.SEMANTIC:
                sections["Rules"].append(m)
            elif m.memory_type == MemoryType.PROCEDURAL:
                sections["Workflows"].append(m)
            elif m.memory_type == MemoryType.EPISODIC:
                sections["Notes"].append(m)
            else:
                sections["Knowledge"].append(m)
        
        output = "# AGENTS.md (Generated by Bilinc)\n"
        output += f"# Bilinc State Plane Export\n\n"
        
        for section, mems in sections.items():
            if mems:
                output += f"## {section}\n\n"
                for m in mems:
                    output += f"- **{m.key}**: {m.value}\n"
                output += "\n"
        
        return output
    
    def _export_to_mcp(self, memories: List[MemoryEntry]) -> str:
        """Export to universal MCP JSON format."""
        data = []
        for m in memories:
            data.append({
                "key": m.key,
                "type": m.memory_type.value,
                "value": m.value,
                "metadata": m.metadata,
                "source": m.source,
                "confidence": m.current_strength,
            })
        return json.dumps(data, indent=2)
    
    def _export_to_generic(self, memories: List[MemoryEntry]) -> str:
        """Export to generic text format."""
        lines = ["# Bilinc Memory Export\n"]
        for m in memories:
            lines.append(f"---\n## {m.key} ({m.memory_type.value})")
            value = m.value if isinstance(m.value, str) else json.dumps(m.value)
            lines.append(value)
            lines.append("")
        return "\n".join(lines)
