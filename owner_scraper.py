import json
import asyncio
import os
from web3 import AsyncWeb3
from web3.middleware import ExtraDataToPOAMiddleware
import aiosqlite
from web3 import AsyncHTTPProvider, AsyncWeb3

async def process_network(network_name, network_config, db_lock):
    rpc_url = network_config['rpc_url']
    blockchain_name = network_config['name']
    step = network_config.get('step', 2000)
    poa = network_config.get('poa', False)
    
    # Use AsyncWeb3
    w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url))
    
    if poa:
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    
    # Database file
    db_file = 'owners.db'
    
    # Connect to the database
    async with aiosqlite.connect(db_file) as conn:
        # Ensure foreign keys are enabled
        await conn.execute('PRAGMA foreign_keys = ON;')
        
        # Create tables if they don't exist (only once per database)
        async with db_lock:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS blockchain (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    from_block INTEGER
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS owner (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT,
                    blockchain_id INTEGER,
                    UNIQUE(address, blockchain_id),
                    FOREIGN KEY(blockchain_id) REFERENCES blockchain(id)
                )
            ''')
            await conn.commit()
        
        # Insert or get blockchain ID and from_block
        async with db_lock:
            cursor = await conn.execute('SELECT id, from_block FROM blockchain WHERE name = ?', (blockchain_name,))
            row = await cursor.fetchone()
            if row:
                blockchain_id, from_block_db = row
                from_block = from_block_db
            else:
                from_block_config = network_config.get('from_block', 0)
                await conn.execute('INSERT INTO blockchain (name, from_block) VALUES (?, ?)', (blockchain_name, from_block_config))
                await conn.commit()
                cursor = await conn.execute('SELECT id, from_block FROM blockchain WHERE name = ?', (blockchain_name,))
                row = await cursor.fetchone()
                blockchain_id, from_block = row
        
        to_block = network_config.get('to_block', 'latest')
        if to_block == 'latest':
            to_block = await w3.eth.block_number
        else:
            to_block = int(to_block)
        
        print(f"[{network_name}] Scanning blocks from {from_block} to {to_block} for ProxyCreation events...")
        
        proxy_creation_topic = '0x4f51faf6c4561ff95f067657e43439f0f856d97c04d9ec9070a6199ad418e235'
        proxy_creation_event_abi = {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "internalType": "address", "name": "proxy", "type": "address"},
                {"indexed": False, "internalType": "address", "name": "singleton", "type": "address"}
            ],
            "name": "ProxyCreation",
            "type": "event"
        }
        
        safe_setup_event_abi = {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "internalType": "address", "name": "initiator", "type": "address"},
                {"indexed": False, "internalType": "address[]", "name": "owners", "type": "address[]"},
                {"indexed": False, "internalType": "uint256", "name": "threshold", "type": "uint256"},
                {"indexed": False, "internalType": "address", "name": "initializer", "type": "address"},
                {"indexed": False, "internalType": "address", "name": "fallbackHandler", "type": "address"}
            ],
            "name": "SafeSetup",
            "type": "event"
        }
        
        # Create contract object to decode ProxyCreation events
        dummy_factory_contract = w3.eth.contract(abi=[proxy_creation_event_abi])
        
        # Compute the topic hash for SafeSetup event
        safe_setup_topic = w3.keccak(text='SafeSetup(address,address[],uint256,address,address)').hex()
        
        last_block_processed = from_block - 1
        
        # Process blocks in steps
        for start_block in range(from_block, to_block + 1, step):
            end_block = min(start_block + step - 1, to_block)
            print(f"[{network_name}] Processing blocks from {start_block} to {end_block}")
            
            # Create filter for ProxyCreation events
            filter_params = {
                'fromBlock': start_block,
                'toBlock': end_block,
                'topics': [proxy_creation_topic]
            }
            
            try:
                logs = await w3.eth.get_logs(filter_params)
            except Exception as e:
                print(f"[{network_name}] Error fetching logs for blocks {start_block} to {end_block}: {e}")
                # Update from_block in the database even if there's an error
                async with db_lock:
                    new_from_block = end_block + 1
                    await conn.execute('UPDATE blockchain SET from_block = ? WHERE id = ?', (new_from_block, blockchain_id))
                    await conn.commit()
                continue
            
            print(f"[{network_name}] Found {len(logs)} ProxyCreation events in blocks {start_block} to {end_block}.")
            
            for log in logs:
                # Update last_block_processed
                if log['blockNumber'] > last_block_processed:
                    last_block_processed = log['blockNumber']
                
                # Decode ProxyCreation event
                try:
                    event = dummy_factory_contract.events.ProxyCreation().process_log(log)
                    proxy_address = event['args']['proxy']
                    print(f"[{network_name}] Processing proxy at address: {proxy_address}")
                except Exception as e:
                    print(f"[{network_name}] Error processing ProxyCreation event: {e}")
                    continue
                
                # Create contract object for the proxy
                proxy_contract = w3.eth.contract(address=proxy_address, abi=[safe_setup_event_abi])
                
                # Fetch SafeSetup event from the proxy contract
                try:
                    # Filter parameters to get SafeSetup event from the proxy
                    setup_filter_params = {
                        'fromBlock': log['blockNumber'],
                        'toBlock': log['blockNumber'],
                        'address': proxy_address,
                        'topics': [safe_setup_topic]
                    }
                    setup_logs = await w3.eth.get_logs(setup_filter_params)
                    
                    if not setup_logs:
                        print(f"[{network_name}] No SafeSetup events found for proxy {proxy_address}")
                        continue
                    
                    setup_log = setup_logs[0]
                    
                    # Decode SafeSetup event
                    setup_event = proxy_contract.events.SafeSetup().process_log(setup_log)
                    owners = setup_event['args']['owners']
                    
                    owner_inserts = []
                    for owner_address in owners:
                        owner_inserts.append((owner_address, blockchain_id))
                        print(f"[{network_name}] Found owner {owner_address}")
                    
                    # Insert owners into the database
                    async with db_lock:
                        await conn.executemany('''
                            INSERT OR IGNORE INTO owner (address, blockchain_id)
                            VALUES (?, ?)
                        ''', owner_inserts)
                        await conn.commit()
                    print(f"[{network_name}] Inserted {len(owners)} owners into the database for proxy {proxy_address}.")
                except Exception as e:
                    print(f"[{network_name}] Error fetching or processing SafeSetup event for proxy {proxy_address}: {e}")
                    continue
            
            # Update from_block in the database after each step
            new_from_block = end_block + 1
            async with db_lock:
                await conn.execute('UPDATE blockchain SET from_block = ? WHERE id = ?', (new_from_block, blockchain_id))
                await conn.commit()
            print(f"[{network_name}] Updated from_block to {new_from_block}")
        
        print(f"[{network_name}] Finished processing.")

async def main():
    # Load configuration
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    networks = config.get('networks', {})
    
    db_lock = asyncio.Lock()
    tasks = []
    for network_name, network_config in networks.items():
        tasks.append(process_network(network_name, network_config, db_lock))
    
    await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == '__main__':
    asyncio.run(main())