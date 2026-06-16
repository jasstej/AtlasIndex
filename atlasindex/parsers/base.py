from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class FunctionInfo(BaseModel):
    name: str
    parameters: List[str]  # List of parameter names
    line_number: int
    docstring: Optional[str] = None

class ClassInfo(BaseModel):
    name: str
    methods: List[str]  # Method names
    inheritance: List[str]  # Parent class names
    line_number: int

class ImportInfo(BaseModel):
    name: str  # e.g., 'requests'
    module: Optional[str] = None  # e.g., 'requests.models'
    line_number: int

class EndpointInfo(BaseModel):
    method: str  # GET, POST, etc.
    path: str
    line_number: int

class ParsedCode(BaseModel):
    functions: List[FunctionInfo] = []
    classes: List[ClassInfo] = []
    imports: List[ImportInfo] = []
    endpoints: List[EndpointInfo] = []

class BaseParser:
    def parse(self, content: str, file_path: str) -> ParsedCode:
        """Parses the content of the file and returns structured code constructs."""
        raise NotImplementedError("Subclasses must implement the parse method")
