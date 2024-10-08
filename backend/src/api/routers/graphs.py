import os

from fastapi import APIRouter
from pydantic import BaseModel

from ...agents.retriever_graph import RetrieverGraph

from langchain_google_vertexai import ChatVertexAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from dotenv import load_dotenv
from typing import Union
import logging

logging.basicConfig(level=os.environ.get('LOGLEVEL', 'INFO').upper())


def get_history_str(chat_history: list[dict[str, str]]) -> str:
    history_str = ''
    for i in chat_history:
        history_str += f"User : {i['User']}\nAI : {i['AI']}\n\n"
    return history_str


class UserInput(BaseModel):
    query: str
    chat_history: list[dict[str, str]] = []
    list_sources: bool = False
    list_context: bool = False


load_dotenv()

required_env_vars = [
    'USE_CUDA',
    'LLM_TEMP',
    'HF_EMBEDDINGS',
    'HF_RERANKER',
    'LLM_MODEL',
]

if any(os.getenv(var) is None for var in required_env_vars):
    raise ValueError('One or more environment variables are not set.')

use_cuda: bool = False
llm_temp: float = 0.0

if str(os.getenv('USE_CUDA')).lower() in ('true'):
    use_cuda = True

llm_temp_str = os.getenv('LLM_TEMP')
if llm_temp_str is not None:
    llm_temp = float(llm_temp_str)

embeddings_type: str = str(os.getenv('EMBEDDINGS_TYPE'))

if embeddings_type == 'HF':
    embeddings_model_name = str(os.getenv('HF_EMBEDDINGS'))
elif embeddings_type == 'GOOGLE_GENAI' or embeddings_type == 'GOOGLE_VERTEXAI':
    embeddings_model_name = str(os.getenv('GOOGLE_EMBEDDINGS'))

embeddings_config = {'type': embeddings_type, 'name': embeddings_model_name}

hf_reranker: str = str(os.getenv('HF_RERANKER'))

llm: Union[ChatGoogleGenerativeAI, ChatVertexAI, ChatOllama]

if os.getenv('LLM_MODEL') == 'ollama':
    model_name = str(os.getenv('OLLAMA_MODEL'))
    llm = ChatOllama(model=model_name, temperature=llm_temp)

elif os.getenv('LLM_MODEL') == 'gemini':
    if os.getenv('GOOGLE_GEMINI') == '1_pro':
        llm = ChatGoogleGenerativeAI(model='gemini-pro', temperature=llm_temp)  # type: ignore
    elif os.getenv('GOOGLE_GEMINI') == '1.5_flash':
        llm = ChatVertexAI(model_name='gemini-1.5-flash', temperature=llm_temp)
    elif os.getenv('GOOGLE_GEMINI') == '1.5_pro':
        llm = ChatVertexAI(model_name='gemini-1.5-pro', temperature=llm_temp)
    else:
        raise ValueError('GOOGLE_GEMINI environment variable not set to a valid value.')

else:
    raise ValueError('LLM_MODEL environment variable not set to a valid value.')

router = APIRouter(prefix='/graphs', tags=['graphs'])

rg = RetrieverGraph(
    llm_model=llm,
    embeddings_config=embeddings_config,
    reranking_model_name=hf_reranker,
    use_cuda=use_cuda,
    inbuit_tool_calling=False,
)
rg.initialize()


@router.post('/agent-retriever')
async def get_agent_response(user_input: UserInput) -> dict[str, Union[str, list[str]]]:
    user_question = user_input.query

    inputs = {
        'messages': [
            ('user', user_question),
        ],
        'chat_history': get_history_str(user_input.chat_history),
    }

    if rg.graph is not None:
        output = list(rg.graph.stream(inputs))
    else:
        raise ValueError('RetrieverGraph not initialized.')

    urls: list[str] = []
    context: list[str] = []

    if (
        isinstance(output, list)
        and len(output) > 2
        and 'generate' in output[2]
        and 'messages' in output[2]['generate']
        and len(output[2]['generate']['messages']) > 0
    ):
        llm_response = output[2]['generate']['messages'][0]
        tool = list(output[-2].keys())[0]
        urls = list(set(output[-2][tool]['urls']))
    else:
        logging.error('LLM response extraction failed')

    if user_input.list_sources and user_input.list_context:
        response = {
            'response': llm_response,
            'sources': (urls),
            'context': (context),
            'tool': tool,
        }
    elif user_input.list_sources:
        response = {'response': llm_response, 'sources': (urls), 'tool': tool}
    elif user_input.list_context:
        response = {'response': llm_response, 'context': (context), 'tool': tool}
    else:
        response = {'response': llm_response, 'tool': tool}

    return response
