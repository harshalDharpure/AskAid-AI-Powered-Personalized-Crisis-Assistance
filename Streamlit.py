import os
import streamlit as st
from snowflake.snowpark.session import Session
from snowflake.snowpark.context import get_active_session
from snowflake.cortex import Complete
from snowflake.core import Root
import pandas as pd
import json

# Snowflake details (ensure these are correct or securely retrieved)
os.environ['SNOWFLAKE_USER'] = 'hdharpure'
os.environ['SNOWFLAKE_USER_PASSWORD'] = 'Harshal@9922'
os.environ['SNOWFLAKE_ACCOUNT'] = 'iorvcvq'
os.environ['SNOWFLAKE_DATABASE'] = 'MEDATLAS_AI_CORTEX_SEARCH_DOCS'
os.environ['SNOWFLAKE_SCHEMA'] = 'DATA'
os.environ['SNOWFLAKE_CORTEX_SEARCH_SERVICE'] = 'MEDATLAS_AI_SEARCH_SERVICE_CS'

# Snowflake connection parameters
connection_params = {
    "account": os.getenv("SNOWFLAKE_ACCOUNT"),
    "user": os.getenv("SNOWFLAKE_USER"),
    "password": os.getenv("SNOWFLAKE_USER_PASSWORD"),
    "database": os.getenv("SNOWFLAKE_DATABASE"),
    "schema": os.getenv("SNOWFLAKE_SCHEMA")
    
}

# Create Snowflake session
snowpark_session = Session.builder.configs(connection_params).create()

# Service parameters
CORTEX_SEARCH_DATABASE = "MEDATLAS_AI_CORTEX_SEARCH_DOCS"
CORTEX_SEARCH_SCHEMA = "DATA"
CORTEX_SEARCH_SERVICE = "MEDATLAS_AI_SEARCH_SERVICE_CS"

# Columns to query in the service
COLUMNS = [
    "chunk",
    "relative_path",
    "category"
]

session = get_active_session()
root = Root(session)

svc = root.databases[CORTEX_SEARCH_DATABASE].schemas[CORTEX_SEARCH_SCHEMA].cortex_search_services[CORTEX_SEARCH_SERVICE]

# Default values
NUM_CHUNKS = 3  # Number of chunks for context
slide_window = 7  # Number of conversations to remember in chat history

# Functions

def config_options():
    st.sidebar.selectbox('Select your model:', (
        'mixtral-8x7b',
        'snowflake-arctic',
        'mistral-large',
        'llama3-8b',
        'llama3-70b',
        'reka-flash',
        'mistral-7b',
        'llama2-70b-chat',
        'gemma-7b'), key="model_name")

    categories = session.table('docs_chunks_table').select('category').distinct().collect()
    cat_list = ['ALL'] + [cat.CATEGORY for cat in categories]
    
    st.sidebar.selectbox('Select what products you are looking for', cat_list, key="category_value")
    st.sidebar.checkbox('Do you want that I remember the chat history?', key="use_chat_history", value=True)
    st.sidebar.checkbox('Debug: Click to see summary generated of previous conversation', key="debug", value=True)
    st.sidebar.button("Start Over", key="clear_conversation", on_click=init_messages)
    st.sidebar.expander("Session State").write(st.session_state)

def init_messages():
    if st.session_state.get("clear_conversation", False) or "messages" not in st.session_state:
        st.session_state.messages = []

def get_similar_chunks_search_service(query):
    if st.session_state.category_value == "ALL":
        response = svc.search(query, COLUMNS, limit=NUM_CHUNKS)
    else:
        filter_obj = {"@eq": {"category": st.session_state.category_value}}
        response = svc.search(query, COLUMNS, filter=filter_obj, limit=NUM_CHUNKS)

    st.sidebar.json(response.json())
    return response.json()

def get_chat_history():
    chat_history = []
    start_index = max(0, len(st.session_state.messages) - slide_window)
    for i in range(start_index, len(st.session_state.messages) - 1):
        chat_history.append(st.session_state.messages[i])
    return chat_history

def summarize_question_with_history(chat_history, question):
    prompt = f"""
        Based on the chat history below and the question, generate a query that extends the question with the chat history provided. 
        The query should be in natural language. Answer with only the query. Do not add any explanation.

        <chat_history>
        {chat_history}
        </chat_history>
        <question>
        {question}
        </question>
        """

    summary = Complete(st.session_state.model_name, prompt)
    if st.session_state.debug:
        st.sidebar.text("Summary to be used to find similar chunks in the docs:")
        st.sidebar.caption(summary)

    return summary.replace("'", "")

def create_prompt(myquestion):
    if st.session_state.use_chat_history:
        chat_history = get_chat_history()
        if chat_history:  # Not the first question
            question_summary = summarize_question_with_history(chat_history, myquestion)
            prompt_context = get_similar_chunks_search_service(question_summary)
        else:
            prompt_context = get_similar_chunks_search_service(myquestion)  # First question
    else:
        prompt_context = get_similar_chunks_search_service(myquestion)
        chat_history = ""

    prompt = f"""
           You are an expert chat assistant that extracts information from the CONTEXT provided
           between <context> and </context> tags.
           You offer a chat experience considering the information included in the CHAT HISTORY
           provided between <chat_history> and </chat_history> tags..
           When answering the question contained between <question> and </question> tags
           be concise and do not hallucinate. 
           If you don’t have the information just say so.

           Do not mention the CONTEXT used in your answer.
           Do not mention the CHAT HISTORY used in your answer.

           Only answer the question if you can extract it from the CONTEXT provided.

           <chat_history>
           {chat_history}
           </chat_history>
           <context>          
           {prompt_context}
           </context>
           <question>  
           {myquestion}
           </question>
           Answer: 
           """

    json_data = json.loads(prompt_context)
    relative_paths = set(item['relative_path'] for item in json_data['results'])

    return prompt, relative_paths

def answer_question(myquestion):
    prompt, relative_paths = create_prompt(myquestion)
    response = Complete(st.session_state.model_name, prompt)
    return response, relative_paths

def display_image_from_url(url):
    """Display image in the sidebar from URL"""
    if url:
        st.sidebar.image(url, caption="Related Document Image", use_column_width=True)

def main():
    st.title(f":speech_balloon: Chat Document Assistant with Snowflake Cortex 🤖")
    st.write("This is the list of documents you already have and that will be used to answer your questions:")

    docs_available = session.sql("ls @docs").collect()
    list_docs = [doc["name"] for doc in docs_available]

    st.dataframe(list_docs)

    config_options()
    init_messages()

    # Display chat history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Accept user input
    if question := st.chat_input("What do you want to know about your products? 💬"):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(f":pencil: {question}")
        
        # Display assistant response in chat message container
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            question = question.replace("'", "")

            with st.spinner(f"{st.session_state.model_name} thinking..."):
                response, relative_paths = answer_question(question)
                response = response.replace("'", "")
                message_placeholder.markdown(f":robot: {response}")

                if relative_paths != "None":
                    with st.sidebar.expander("Related Documents 📄"):
                        for path in relative_paths:
                            cmd2 = f"select GET_PRESIGNED_URL(@docs, '{path}', 360) as URL_LINK from directory(@docs)"
                            df_url_link = session.sql(cmd2).to_pandas()
                            url_link = df_url_link._get_value(0, 'URL_LINK')

                            display_url = f"Doc: [{path}]({url_link})"
                            st.sidebar.markdown(display_url)

                            # Displaying image if the relative path is an image
                            if 'image' in path.lower():
                                display_image_from_url(url_link)

        st.session_state.messages.append({"role": "assistant", "content": response})

if __name__ == "__main__":
    main()
