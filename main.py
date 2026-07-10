import os
import fitz
import streamlit as st
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
)
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from docx import Document

# Load environment variables
load_dotenv()

# Azure AI Search setup
search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
search_key = os.getenv("AZURE_SEARCH_KEY")
index_name = os.getenv("AZURE_SEARCH_INDEX")

# Azure OpenAI setup
openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)


# Create search index
def create_index():
    index_client = SearchIndexClient(
        endpoint=search_endpoint,
        credential=AzureKeyCredential(search_key),
    )

    fields = [
        SimpleField(name="id", type="Edm.String", key=True),
        SearchableField(name="content", type="Edm.String"),
        SearchableField(name="document_name", type="Edm.String"),
    ]

    index = SearchIndex(name=index_name, fields=fields)
    index_client.create_or_update_index(index)


if "index_created" not in st.session_state:
    try:
        create_index()
        st.session_state.index_created = True
    except Exception:
        st.session_state.index_created = True


# Streamlit UI
st.title("📄 AskMyDocs")
st.caption("Upload a file. Ask anything from it.")

# Step 1 - Upload files
st.subheader("Step 1 — Upload your file")

uploaded_files = st.file_uploader(
    "Choose up to 2 files",
    type=["pdf", "docx", "txt", "md"],
    accept_multiple_files=True,
)

if len(uploaded_files) > 2:
    st.error("You can only upload up to 2 files.")
    st.stop()

if uploaded_files:

    # Create Search Client only once
    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(search_key),
    )

    # Process every uploaded file
    for uploaded_file in uploaded_files:

        file_extension = uploaded_file.name.split(".")[-1].lower()

        if file_extension == "pdf":
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            text = ""

            for page in doc:
                text += page.get_text()

            doc.close()

        elif file_extension == "docx":
            document = Document(uploaded_file)
            text = "\n".join([para.text for para in document.paragraphs])

        elif file_extension in ["txt", "md"]:
            text = uploaded_file.read().decode("utf-8")

        else:
            st.error(f"Unsupported file format: {uploaded_file.name}")
            continue

        # Split into chunks
        chunks = [
            text[i:i + 1000]
            for i in range(0, len(text), 1000)
        ]

        # Safe filename for Azure Search document ID
        safe_filename = (
            uploaded_file.name
            .replace(".", "_")
            .replace(" ", "_")
        )

        # Upload to Azure AI Search
        documents = [
            {
                "id": f"{safe_filename}_{i}",
                "content": chunk,
                "document_name": uploaded_file.name,
            }
            for i, chunk in enumerate(chunks)
        ]

        search_client.upload_documents(documents)

        st.success(
            f"✅ Uploaded {len(chunks)} chunks from {uploaded_file.name}"
        )

    # Step 2 - Ask Question
    st.subheader("Step 2 — Ask a question")

    question = st.text_input("Type your question here...")

    if st.button("Ask"):

        results = list(search_client.search(question, top=3))

        context = "\n".join(
            r["content"] for r in results
        )

        source = (
            results[0]["document_name"]
            if results
            else "Unknown"
        )

        response = openai_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {
                    "role": "system",
                    "content": f"Answer only from this document: {context}",
                },
                {
                    "role": "user",
                    "content": question,
                },
            ],
            max_completion_tokens=2000,
        )

        st.write("**Source Document:**")
        st.write(source)

        st.write("**Answer:**")
        st.write(response.choices[0].message.content)