"""
Native prompt security scanning and context composition analytics.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional


SECURITY_PATTERNS = [
    ("role_hijack_ignore", "high", re.compile(r"ignore\s+all\s+previous\s+instructions", re.I)),
    ("role_confusion", "medium", re.compile(r"\b(always\s+respond|never\s+mention|you\s+are\s+a\s+helpful\s+ai)\b", re.I)),
    ("credential_openai", "high", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}", re.I)),
    ("credential_github", "high", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}", re.I)),
    ("credential_aws_key", "high", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("credential_private_key", "high", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("suspicious_unicode", "info", re.compile(r"[\u200B-\u200F\u202A-\u202E\u2066-\u2069]")),
]

SEVERITY_SCORES = {"info": 20, "medium": 60, "high": 90, "critical": 100}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item.get("text"))
                elif isinstance(item.get("content"), str):
                    parts.append(item.get("content"))
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value.get("text")
        if isinstance(value.get("content"), str):
            return value.get("content")
    return str(value)


def _redact_preview(text: str) -> str:
    preview = (text or "").strip().replace("\n", " ")[:120]
    preview = re.sub(r"sk-(?:proj-)?[A-Za-z0-9_-]{8,}", "[redacted-openai-key]", preview, flags=re.I)
    preview = re.sub(r"gh[pousr]_[A-Za-z0-9]{8,}", "[redacted-github-token]", preview)
    preview = re.sub(r"\bAKIA[0-9A-Z]{16}\b", "[redacted-aws-key]", preview)
    return preview


def analyze_prompt_payload(request_data: Dict[str, Any], model_name: Optional[str] = None) -> Dict[str, Any]:
    messages = request_data.get("messages") or []
    findings: List[Dict[str, Any]] = []
    role_counts: Dict[str, int] = {}
    token_distribution = {
        "system": 0,
        "user": 0,
        "assistant": 0,
        "tool": 0,
        "other": 0,
    }

    segments: List[Dict[str, Any]] = []
    for index, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "other")
        text = _normalize_text(msg.get("content"))
        token_estimate = max(0, len(text) // 4)
        role_counts[role] = role_counts.get(role, 0) + 1
        bucket = role if role in token_distribution else "other"
        token_distribution[bucket] += token_estimate
        segments.append({"role": role, "text": text, "message_index": index})

    input_text = _normalize_text(request_data.get("input"))
    prompt_text = _normalize_text(request_data.get("prompt"))
    if input_text:
        segments.append({"role": "input", "text": input_text, "message_index": None})
        token_distribution["other"] += max(0, len(input_text) // 4)
    if prompt_text:
        segments.append({"role": "prompt", "text": prompt_text, "message_index": None})
        token_distribution["other"] += max(0, len(prompt_text) // 4)

    for segment in segments:
        role = segment["role"]
        if role in {"system", "developer"}:
            continue
        text = segment["text"]
        for pattern_id, severity, pattern in SECURITY_PATTERNS:
            match = pattern.search(text or "")
            if not match:
                continue
            findings.append({
                "category": pattern_id,
                "severity": severity,
                "detector": "regex_v1",
                "span_label": role,
                "message_index": segment["message_index"],
                "evidence_preview": _redact_preview(match.group(0) if severity == "info" else text),
                "metadata": {"pattern_id": pattern_id},
            })

    max_score = max((SEVERITY_SCORES.get(item["severity"], 0) for item in findings), default=0)
    risk_level = "none"
    if max_score >= 90:
        risk_level = "high"
    elif max_score >= 60:
        risk_level = "medium"
    elif max_score > 0:
        risk_level = "info"

    total_tokens = sum(token_distribution.values())
    composition = {
        "message_count": len(messages),
        "role_counts": role_counts,
        "token_distribution": token_distribution,
        "tool_count": len(request_data.get("tools") or []),
        "has_system_prompt": bool(role_counts.get("system")),
        "has_tools": bool(request_data.get("tools")),
        "context_utilization_pct": 0.0,
        "largest_segment_role": max(token_distribution, key=token_distribution.get) if total_tokens else None,
        "prompt_shape": "+".join(sorted(role_counts.keys())) if role_counts else "empty",
    }

    payload_fingerprint = hashlib.sha256(
        repr({
            "model": model_name or request_data.get("model"),
            "messages": messages,
            "input": request_data.get("input"),
            "prompt": request_data.get("prompt"),
        }).encode("utf-8")
    ).hexdigest()

    return {
        "request_hash": payload_fingerprint,
        "risk_level": risk_level,
        "risk_score": max_score,
        "findings": findings,
        "summary": {
            "findings_count": len(findings),
            "high_count": sum(1 for item in findings if item["severity"] == "high"),
            "medium_count": sum(1 for item in findings if item["severity"] == "medium"),
            "info_count": sum(1 for item in findings if item["severity"] == "info"),
        },
        "composition": composition,
    }
