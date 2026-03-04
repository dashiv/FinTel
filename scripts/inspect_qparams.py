import streamlit
print(streamlit.query_params)
print(type(streamlit.query_params))
from streamlit.runtime.state import QueryParamsProxy
print(QueryParamsProxy)
print([m for m in dir(streamlit.query_params) if not m.startswith('_')])
