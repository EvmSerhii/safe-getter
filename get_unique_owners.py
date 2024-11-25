import sqlite3

# Connect to the SQLite database
conn = sqlite3.connect('owners.db')
cursor = conn.cursor()

# Query to count unique owner addresses
cursor.execute('''
    SELECT COUNT(DISTINCT address) FROM owner
''')

# Fetch the count of unique owner addresses
unique_owner_count = cursor.fetchone()[0]

# Close the database connection
conn.close()

# Print the count of unique owner addresses
print("Total number of unique owner addresses:")
print(unique_owner_count)