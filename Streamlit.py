import streamlit as st
from snowflake.snowpark import Session
from snowflake.cortex import Complete
from snowflake.core import Root
import pandas as pd
import traceback

# Set max column width for pandas
pd.set_option("max_colwidth", None)

# Snowflake connection parameters (update with your actual credentials)
connection_parameters = {
    "user": "hdharpure",
    "password": "Harshal@9922",
    "account": "qu81872.ap-south-1.aws",
    "warehouse": "COMPUTE_WH",
    "database": "MEDATLAS_AI_CORTEX_SEARCH_DOCS",
    "schema": "DATA"
}

# Default values for service parameters
NUM_CHUNKS = 3
slide_window = 7
CORTEX_SEARCH_DATABASE = "MEDATLAS_AI_CORTEX_SEARCH_DOCS"
CORTEX_SEARCH_SCHEMA = "DATA"
CORTEX_SEARCH_SERVICE = "MEDATLAS_AI_SEARCH_SERVICE_CS"
COLUMNS = ["chunk", "relative_path", "category"]

# Function to create a Snowpark session
def create_snowpark_session():
    try:
        session = Session.builder.configs(connection_parameters).create()
        st.success("Successfully connected to Snowflake.")
        return session
    except Exception as e:
        st.error("Error creating Snowpark session:")
        st.error(traceback.format_exc())
        return None

# Initialize Snowflake session
session = create_snowpark_session()
if session is None:
    st.stop()

# Root and service initialization
try:
    root = Root(session)
    svc = root.databases[CORTEX_SEARCH_DATABASE].schemas[CORTEX_SEARCH_SCHEMA].cortex_search_services[CORTEX_SEARCH_SERVICE]
except Exception as e:
    st.error("Error initializing Cortex service:")
    st.error(traceback.format_exc())
    st.stop()

# Sidebar configuration options
def config_options():
    st.sidebar.selectbox(
        'Select your model:',
        ['mixtral-8x7b', 'snowflake-arctic', 'mistral-large', 'llama3-8b', 'llama3-70b',
         'reka-flash', 'mistral-7b', 'llama2-70b-chat', 'gemma-7b'],
        key="model_name"
    )

    # Fetch distinct categories
    try:
        categories = session.table('docs_chunks_table').select('category').distinct().collect()
        cat_list = ['ALL'] + [cat.CATEGORY for cat in categories]
        st.sidebar.selectbox('Select product category:', cat_list, key="category_value")
    except Exception as e:
        st.error("Error fetching categories:")
        st.error(traceback.format_exc())
        st.stop()

    st.sidebar.checkbox('Remember chat history?', key="use_chat_history", value=True)
    st.sidebar.checkbox('Debug: Show query summary', key="debug", value=True)
    st.sidebar.button("Start Over", key="clear_conversation", on_click=init_messages)
    st.sidebar.expander("Session State").write(st.session_state)

# Initialize chat history
def init_messages():
    if st.session_state.get("clear_conversation", False) or "messages" not in st.session_state:
        st.session_state.messages = []

# Function to query similar chunks
def get_similar_chunks_search_service(query):
    try:
        if st.session_state.category_value == "ALL":
            response = svc.search(query, COLUMNS, limit=NUM_CHUNKS)
        else:
            filter_obj = {"@eq": {"category": st.session_state.category_value}}
            response = svc.search(query, COLUMNS, filter=filter_obj, limit=NUM_CHUNKS)
        return response.json()
    except Exception as e:
        st.error("Error querying Cortex service:")
        st.error(traceback.format_exc())
        return None

# Summarize the chat history for query context
def summarize_question_with_history(chat_history, question):
    try:
        prompt = f"""
            Based on the chat history below and the question, generate a query that extends the question 
            with the chat history provided. Only return the query, no explanation.

            <chat_history>
            {chat_history}
            </chat_history>
            <question>
            {question}
            </question>
        """
        return Complete(st.session_state.model_name, prompt)
    except Exception as e:
        st.error("Error summarizing question with chat history:")
        st.error(traceback.format_exc())
        return None

# Main prompt creation logic
def create_prompt(myquestion):
    chat_history = (
        st.session_state.messages[-slide_window:] if st.session_state.get("use_chat_history") else []
    )

    if chat_history:
        question_summary = summarize_question_with_history(chat_history, myquestion)
        prompt_context = get_similar_chunks_search_service(question_summary)
    else:
        prompt_context = get_similar_chunks_search_service(myquestion)

    return f"""
        Extract information from the CONTEXT provided below.
        <context>
        {prompt_context}
        </context>
        <question>
        {myquestion}
        </question>
    """, prompt_context

# Answer the user question
def answer_question(myquestion):
    prompt, context = create_prompt(myquestion)
    try:
        response = Complete(st.session_state.model_name, prompt)
        return response, context
    except Exception as e:
        st.error("Error answering question:")
        st.error(traceback.format_exc())
        return None, None

# Main app logic
def main():
    st.title(":speech_balloon: Chat Document Assistant with Snowflake Cortex 🤖")
    st.write("Available documents:") 

    # List available documents
    try:
        docs_available = session.sql("ls @docs").collect()
        st.dataframe([doc["name"] for doc in docs_available])
    except Exception as e:
        st.error("Error listing documents:")
        st.error(traceback.format_exc())

    config_options()
    init_messages()

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Handle user input
    if question := st.chat_input("What do you want to know?"):
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner(f"Fetching response..."):
                response, context = answer_question(question)
                if response:
                    st.markdown(response)
                else:
                    st.error("Unable to fetch a response.")

if __name__ == "__main__":
    main()
