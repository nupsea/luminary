import asyncio
import logging
import uuid
from sqlalchemy import select
from app.database import get_session_factory
from app.models import DocumentModel, ChunkModel, CodeSnippetModel
from app.workflows.ingestion import entity_extract_node, IngestionState

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("repopulate_graph")

async def repopulate():
    async with get_session_factory()() as session:
        # Fetch all completed documents
        stmt = select(DocumentModel).where(DocumentModel.stage == "complete")
        result = await session.execute(stmt)
        docs = result.scalars().all()
        
        logger.info(f"Found {len(docs)} documents to process.")
        
        for doc in docs:
            logger.info(f"Processing: {doc.title} ({doc.id})")
            
            # Fetch chunks
            chunk_stmt = select(ChunkModel).where(ChunkModel.document_id == doc.id).order_by(ChunkModel.chunk_index)
            chunk_result = await session.execute(chunk_stmt)
            chunks = chunk_result.scalars().all()
            
            # For code documents, we need to restore function_name metadata for the call graph
            code_snippets = {}
            if doc.content_type == "code":
                snippet_stmt = select(CodeSnippetModel).where(CodeSnippetModel.document_id == doc.id)
                snippet_result = await session.execute(snippet_stmt)
                for s in snippet_result.scalars().all():
                    code_snippets[s.chunk_id] = s
            
            chunk_dicts = []
            for c in chunks:
                cd = {
                    "id": c.id,
                    "document_id": c.document_id,
                    "text": c.text,
                    "index": c.chunk_index
                }
                # Restore code metadata if available
                if c.id in code_snippets:
                    s = code_snippets[c.id]
                    # Signature usually contains the name for functions
                    if s.signature:
                        cd["function_name"] = s.signature.split('(')[0].split()[-1]
                        cd["body_text"] = s.content
                chunk_dicts.append(cd)
            
            state: IngestionState = {
                "document_id": doc.id,
                "file_path": doc.file_path,
                "format": doc.format,
                "parsed_document": None,
                "content_type": doc.content_type,
                "chunks": chunk_dicts,
                "status": "entity_extract"
            }
            
            try:
                await entity_extract_node(state)
                logger.info(f"Successfully repopulated graph for {doc.id}")
            except Exception as e:
                logger.error(f"Failed to process {doc.id}: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(repopulate())
