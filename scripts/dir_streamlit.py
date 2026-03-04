import streamlit
print([a for a in dir(streamlit) if 'query' in a.lower()])
print([a for a in dir(streamlit) if 'rerun' in a.lower()])
