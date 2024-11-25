# Owners scraper from Safe

### To start working with script

- Python 3.11+
- Virtualenv installed `pip3 install virtualenv`
- Create virtualenv `python3 -m venv venv`
- Activate virtualenv `source /path/to/venv/bin/activate`
- Download needed packages `pip3 install -r requirements.txt`

### To start script

- Be in created virtualenv
- Run `python3 owner_scraper.py`
- It should create an sqlite database where it will store owners from networks
- To get count of unique owners run `python3 get_unique_owners.py`
- To get count of unique owners by blockchain run `python3 get_unique_owners_by_network.py`

### To add new networks

- Go to `config.json`
- Add network as example:
  - "Network name": {
    "name": "Network name",
    "rpc_url": "Rpc_url",
    "from_block": starting block,
    "to_block": ending block ('latest'),
    "step": number of blocks to check (limited by rpc),
    "poa": false
    }
