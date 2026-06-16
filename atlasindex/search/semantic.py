import os
import json
import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from atlasindex.storage.models import Project, File, Function, Class

logger = logging.getLogger(__name__)

# Try to load FAISS and SentenceTransformers. If they fail, fall back to keyword search.
ML_SEARCH_AVAILABLE = False
try:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer
    ML_SEARCH_AVAILABLE = True
except ImportError:
    logger.warning("ML packages (faiss-cpu, sentence-transformers, numpy) are missing. Semantic search will use SQL Keyword fallback.")

INDEX_DIR = os.path.expanduser("~/.atlasindex")
FAISS_INDEX_PATH = os.path.join(INDEX_DIR, "semantic_index.faiss")
MAPPING_PATH = os.path.join(INDEX_DIR, "semantic_mapping.json")

class SemanticSearchEngine:
    def __init__(self):
        global ML_SEARCH_AVAILABLE
        self.model = None
        self.index = None
        self.mapping = []  # Maps index offset -> dict of metadata
        
        if ML_SEARCH_AVAILABLE:
            try:
                os.makedirs(INDEX_DIR, exist_ok=True)
                # Load model
                logger.info("Loading sentence-transformers model (all-MiniLM-L6-v2)...")
                self.model = SentenceTransformer("all-MiniLM-L6-v2")
                self.dimension = 384  # Dimension of all-MiniLM-L6-v2 embeddings
                
                # Load existing index if it exists
                if os.path.exists(FAISS_INDEX_PATH) and os.path.exists(MAPPING_PATH):
                    logger.info("Loading existing FAISS index from disk...")
                    self.index = faiss.read_index(FAISS_INDEX_PATH)
                    with open(MAPPING_PATH, "r") as f:
                        self.mapping = json.load(f)
                else:
                    logger.info("Creating new FAISS index...")
                    self.index = faiss.IndexFlatL2(self.dimension)
                    self.mapping = []
            except Exception as e:
                logger.error(f"Failed to initialize ML semantic search: {e}. Switching to SQL fallback.")
                ML_SEARCH_AVAILABLE = False

    def build_index_from_db(self, db: Session) -> None:
        """Scan all indexed functions, classes and files in DB, embed them, and save FAISS index."""
        if not ML_SEARCH_AVAILABLE:
            return

        logger.info("Re-indexing code snippets for semantic search...")
        
        # Collect snippets
        snippets = []
        
        # 1. Fetch functions
        funcs = db.query(Function).all()
        for f in funcs:
            file_record = db.query(File).filter(File.id == f.file_id).first()
            if not file_record:
                continue
            project_record = db.query(Project).filter(Project.id == file_record.project_id).first()
            
            snippet_text = f"Function {f.name}({', '.join(f.parameters or [])}):\n{f.docstring or ''}"
            snippets.append({
                "type": "function",
                "name": f.name,
                "project": project_record.name if project_record else "Unknown",
                "file": file_record.path,
                "line": f.line_number,
                "text": snippet_text
            })

        # 2. Fetch classes
        classes = db.query(Class).all()
        for c in classes:
            file_record = db.query(File).filter(File.id == c.file_id).first()
            if not file_record:
                continue
            project_record = db.query(Project).filter(Project.id == file_record.project_id).first()
            
            snippet_text = f"Class {c.name} (inherits: {', '.join(c.inheritance or [])}):\nmethods: {', '.join(c.methods or [])}"
            snippets.append({
                "type": "class",
                "name": c.name,
                "project": project_record.name if project_record else "Unknown",
                "file": file_record.path,
                "line": c.line_number,
                "text": snippet_text
            })

        # 3. Fetch all files and chunk their content
        files = db.query(File).all()
        for f in files:
            project_record = db.query(Project).filter(Project.id == f.project_id).first()
            if not project_record:
                continue
            
            file_abs_path = os.path.join(project_record.path, f.path)
            if not os.path.exists(file_abs_path):
                continue
                
            try:
                with open(file_abs_path, "r", encoding="utf-8", errors="ignore") as file_obj:
                    content = file_obj.read()
                
                # Split content into chunks of 800 characters (roughly 15-20 lines) with 200 characters overlap
                chunk_size = 800
                overlap = 200
                
                i = 0
                while i < len(content):
                    chunk_text = content[i : i + chunk_size]
                    # Estimate starting line number
                    start_line = content[:i].count("\n") + 1
                    
                    snippets.append({
                        "type": "code_chunk",
                        "name": os.path.basename(f.path),
                        "project": project_record.name,
                        "file": f.path,
                        "line": start_line,
                        "text": chunk_text
                    })
                    
                    i += (chunk_size - overlap)
            except Exception as e:
                logger.debug(f"Failed to read file {file_abs_path} for chunking: {e}")

        if not snippets:
            logger.info("No snippets found to index.")
            return

        try:
            # Recreate clean index
            self.index = faiss.IndexFlatL2(self.dimension)
            self.mapping = snippets
            
            # Compute embeddings
            texts = [s["text"] for s in snippets]
            embeddings = self.model.encode(texts, show_progress_bar=False)
            embeddings_np = np.array(embeddings).astype("float32")
            
            # Add to FAISS
            self.index.add(embeddings_np)
            
            # Save to disk
            faiss.write_index(self.index, FAISS_INDEX_PATH)
            with open(MAPPING_PATH, "w") as f:
                json.dump(self.mapping, f)
                
            logger.info(f"Successfully indexed {len(snippets)} snippets for semantic search.")
        except Exception as e:
            logger.error(f"Failed to build semantic index: {e}")

    def search(self, query: str, db: Session, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Searches the index.
        - If ML search is available, uses FAISS query.
        - Otherwise, performs a standard SQL LIKE / Regex fallback.
        """
        if ML_SEARCH_AVAILABLE and self.index and self.index.ntotal > 0:
            try:
                # Embed query
                query_vector = self.model.encode([query])
                query_vector_np = np.array(query_vector).astype("float32")
                
                # Search FAISS (returns distances and offsets)
                distances, indices = self.index.search(query_vector_np, min(limit, self.index.ntotal))
                
                results = []
                for i, idx in enumerate(indices[0]):
                    if idx == -1 or idx >= len(self.mapping):
                        continue
                    meta = self.mapping[idx]
                    results.append({
                        "type": meta["type"],
                        "name": meta["name"],
                        "project": meta["project"],
                        "file": meta["file"],
                        "line": meta["line"],
                        "snippet": meta["text"],
                        "score": float(distances[0][i])
                    })
                return results
            except Exception as e:
                logger.error(f"Semantic search failed: {e}. Falling back to keyword search.")

        # SQL Fallback
        logger.info(f"Running keyword SQL search for query: '{query}'")
        results = []
        
        # Check functions
        funcs = db.query(Function).filter(
            (Function.name.like(f"%{query}%")) | (Function.docstring.like(f"%{query}%"))
        ).limit(limit).all()
        
        for f in funcs:
            file_record = db.query(File).filter(File.id == f.file_id).first()
            if not file_record:
                continue
            project_record = db.query(Project).filter(Project.id == file_record.project_id).first()
            results.append({
                "type": "function",
                "name": f.name,
                "project": project_record.name if project_record else "Unknown",
                "file": file_record.path,
                "line": f.line_number,
                "snippet": f"Function {f.name}({', '.join(f.parameters or [])}):\n{f.docstring or ''}",
                "score": 1.0  # Equal score for keyword matches
            })

        # Check classes
        classes = db.query(Class).filter(Class.name.like(f"%{query}%")).limit(limit).all()
        for c in classes:
            file_record = db.query(File).filter(File.id == c.file_id).first()
            if not file_record:
                continue
            project_record = db.query(Project).filter(Project.id == file_record.project_id).first()
            results.append({
                "type": "class",
                "name": c.name,
                "project": project_record.name if project_record else "Unknown",
                "file": file_record.path,
                "line": c.line_number,
                "snippet": f"Class {c.name} (inherits: {', '.join(c.inheritance or [])}):\nmethods: {', '.join(c.methods or [])}",
                "score": 1.0
            })

        # Check actual file contents (substring search / grep)
        files = db.query(File).all()
        for f in files:
            project_record = db.query(Project).filter(Project.id == f.project_id).first()
            if not project_record:
                continue
            file_abs_path = os.path.join(project_record.path, f.path)
            if not os.path.exists(file_abs_path):
                continue
                
            try:
                with open(file_abs_path, "r", encoding="utf-8", errors="ignore") as file_obj:
                    content = file_obj.read()
                
                query_lower = query.lower()
                content_lower = content.lower()
                
                if query_lower in content_lower:
                    lines = content.splitlines()
                    for line_idx, line_text in enumerate(lines, 1):
                        if query_lower in line_text.lower():
                            start_ctx = max(0, line_idx - 3)
                            end_ctx = min(len(lines), line_idx + 3)
                            snippet = "\n".join(lines[start_ctx:end_ctx])
                            
                            results.append({
                                "type": "code_chunk",
                                "name": os.path.basename(f.path),
                                "project": project_record.name,
                                "file": f.path,
                                "line": line_idx,
                                "snippet": snippet,
                                "score": 1.0
                            })
                            if len(results) >= limit * 3:
                                break
            except Exception as e:
                logger.debug(f"Failed to search file {file_abs_path} content: {e}")

        return results[:limit]
