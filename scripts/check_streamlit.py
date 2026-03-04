import streamlit
print(streamlit.__version__)
print('setter', hasattr(streamlit,'experimental_set_query_params'))
print('rerun', hasattr(streamlit,'experimental_rerun'))
