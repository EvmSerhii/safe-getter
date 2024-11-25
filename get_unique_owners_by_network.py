import sqlite3

# Connect to the SQLite database
conn = sqlite3.connect('owners.db')
cursor = conn.cursor()

# Query to get unique owner counts per blockchain
cursor.execute('''
    SELECT blockchain.name, COUNT(DISTINCT owner.address) AS owner_count
    FROM owner
    JOIN blockchain ON owner.blockchain_id = blockchain.id
    GROUP BY owner.blockchain_id
''')

# Fetch all rows
owner_counts = cursor.fetchall()

# Close the database connection
conn.close()

# Print the counts per blockchain
print("Unique Owner Counts per Blockchain:")
for blockchain_name, count in owner_counts:
    print(f"{blockchain_name}: {count}")