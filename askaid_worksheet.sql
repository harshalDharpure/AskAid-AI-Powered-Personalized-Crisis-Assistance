-- Create the database for MedAtlas AI project
CREATE DATABASE MEDATLAS_AI_CORTEX_SEARCH_DOCS;
CREATE SCHEMA DATA;

SHOW CORTEX SEARCH SERVICES IN SCHEMA DATA;
ALTER ACCOUNT SET NETWORK_POLICY = allow_all_policy;

-- Create the text chunker function to split PDF text into chunks
CREATE OR REPLACE FUNCTION text_chunker(pdf_text STRING)
RETURNS TABLE (chunk VARCHAR)
LANGUAGE PYTHON
RUNTIME_VERSION = '3.9'
HANDLER = 'text_chunker'
PACKAGES = ('snowflake-snowpark-python', 'langchain')
AS
$$
from snowflake.snowpark.types import StringType, StructField, StructType
from langchain.text_splitter import RecursiveCharacterTextSplitter
import pandas as pd

class text_chunker:

    def process(self, pdf_text: str):
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size = 1512, # Adjust this as you see fit
            chunk_overlap  = 256, # This lets text have some form of overlap. Useful for keeping chunks contextual
            length_function = len
        )
    
        chunks = text_splitter.split_text(pdf_text)
        df = pd.DataFrame(chunks, columns=['chunks'])
        
        yield from df.itertuples(index=False, name=None)
$$;

-- Create a stage for storing the PDFs
CREATE OR REPLACE STAGE docs 
ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE') 
DIRECTORY = (ENABLE = TRUE);

-- List the files in the stage
LS @docs;

-- Create a table to store the chunks of text
CREATE OR REPLACE TABLE DOCS_CHUNKS_TABLE ( 
    RELATIVE_PATH VARCHAR(16777216), -- Relative path to the PDF file
    SIZE NUMBER(38,0), -- Size of the PDF
    FILE_URL VARCHAR(16777216), -- URL for the PDF
    SCOPED_FILE_URL VARCHAR(16777216), -- Scoped URL (you can choose which one to keep depending on your use case)
    CHUNK VARCHAR(16777216), -- Piece of text
    CATEGORY VARCHAR(16777216) -- Will hold the document category to enable filtering
);

-- Insert data into the chunks table
INSERT INTO docs_chunks_table (relative_path, size, file_url,
                               scoped_file_url, chunk)
    SELECT relative_path, 
           size,
           file_url, 
           build_scoped_file_url(@docs, relative_path) AS scoped_file_url,
           func.chunk AS chunk
    FROM 
        DIRECTORY(@docs),
        TABLE(text_chunker (TO_VARCHAR(SNOWFLAKE.CORTEX.PARSE_DOCUMENT(@docs, 
                              relative_path, {'mode': 'LAYOUT'})))) AS func;

-- Create a temporary table for document categories
CREATE OR REPLACE TEMPORARY TABLE docs_categories AS WITH unique_documents AS (
    SELECT
        DISTINCT relative_path
    FROM
        docs_chunks_table
),
docs_category_cte AS (
    SELECT
        relative_path,
        TRIM(snowflake.cortex.COMPLETE (
            'llama3-70b',
            'Given the name of the file between <file> and </file> determine if it is related to rare diseases or general health. Use only one word <file> ' || relative_path || '</file>'
        ), '\n') AS category
    FROM
        unique_documents
)
SELECT
    *
FROM
    docs_category_cte;

-- Retrieve the distinct categories
SELECT category FROM docs_categories GROUP BY category;

-- Update the chunks table with the categories
UPDATE docs_chunks_table 
SET category = docs_categories.category
FROM docs_categories
WHERE docs_chunks_table.relative_path = docs_categories.relative_path;

-- Create a search service based on the chunks and categories
CREATE OR REPLACE CORTEX SEARCH SERVICE MEDATLAS_AI_SEARCH_SERVICE_CS
ON chunk
ATTRIBUTES category
WAREHOUSE = COMPUTE_WH
TARGET_LAG = '1 minute'
AS (
    SELECT chunk,
           relative_path,
           file_url,
           category
    FROM docs_chunks_table
);
