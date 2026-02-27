from qfinzero.clients.upq import UPQClient
from collections import defaultdict
import json

maturity = ['10_year', '1_month', '1_year', '2_year', '30_year', '3_month', '5_year']
yield_data = defaultdict(dict)  # Fixed: Allows nested dictionary assignment



def main():
    with UPQClient() as upq:
        print("=== Treasury Yields - All Tenors (2025) ===\n")
        yields_h1 = upq.rates(start="2025-01-02", end="2025-06-30")
        yields_h2 = upq.rates(start="2025-07-01", end="2025-12-31")
        
        yields = yields_h1 + yields_h2  # Combine

        if yields:
            tenor_keys = [k for k in yields[0].keys() if k.startswith("yield_")]
            
           
            header = f"{'Date':^10} |" + "|".join(f"{k.replace('yield_', ''):>8}" for k in tenor_keys)
            print(header)
            print("-" * len(header))

            for row in yields:
                vals_list = [f"{row.get(k, 0):8.2f}" for k in tenor_keys]
                vals = " ".join(vals_list)
                print(vals)
                for i, k in enumerate(tenor_keys):
                    clean_key = k.replace('yield_', '')
                    yield_data[clean_key][row['date']] = vals_list[i].strip()
                
                print(f"{row['date']:^10} |{vals}")

            print(f"\n{len(yields)} trading days processed")
        else:
            print("No rates data found.")
            
    with open('interest_rate_2025.json', 'w') as f:
        json.dump(yield_data, f, indent=2)
            
if __name__ == "__main__":
    main()
    
   
    