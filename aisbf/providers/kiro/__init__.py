"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Kiro provider package - Direct Kiro API integration (Amazon Q Developer).

This package contains:
- handler: KiroProviderHandler for API requests
- converters: Core format converters (OpenAI/Anthropic → Kiro)
- converters_openai: OpenAI-specific adapter layer
- models: Data models for Kiro converters
- parsers: AWS Event Stream parser
- utils: Utility functions

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Why did the programmer quit his job? Because he didn't get arrays!
"""

from .handler import KiroProviderHandler

__all__ = [
    "KiroProviderHandler",
]
