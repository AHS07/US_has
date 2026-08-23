Medicine catalog seed data
==========================

Drop the Kaggle "A-Z Medicine Dataset of India" CSV file into this directory.

Expected filename: az_medicine_dataset_india.csv

Only the "name" column is used. Dosage, price, manufacturer, and composition
are intentionally not imported — those are always entered by the doctor.

Before seeding, extract and deduplicate names into a separate file:

  PowerShell (Windows):
    Import-Csv .\az_medicine_dataset_india.csv | Select-Object -ExpandProperty name | Sort-Object -Unique | Out-File -Encoding utf8 az_medicine_names_deduped.csv

  Or with Python (from healthflow/ root):
    python -c "
    import csv, sys
    names = set()
    with open('data/medicine_seed/az_medicine_dataset_india.csv', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            name = row.get('name','').strip()
            if name:
                names.add(name)
    with open('data/medicine_seed/az_medicine_names_deduped.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['name'])
        for n in sorted(names, key=str.lower):
            w.writerow([n])
    print(f'Wrote {len(names)} names.')
    "

Then seed into Postgres (with Docker running):

  docker compose exec -T postgres psql -U healthflow healthflow \
    -c "\copy medicine_catalog(name) FROM STDIN WITH (FORMAT csv, HEADER true)" \
    < healthflow/data/medicine_seed/az_medicine_names_deduped.csv

All seeded rows get status='active', added_by=NULL (distinguishes bulk-seed from doctor-added entries).

This directory is git-ignored for the CSV files (they can be large).
The README is committed; the CSVs are not.
