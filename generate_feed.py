import os
import requests
import xml.etree.ElementTree as ET

SHOP_URL = os.environ.get("SHOP_URL")         # Es: zx7y17-gz.myshopify.com
CLIENT_ID = os.environ.get("CLIENT_ID")       # Il Client ID della tua app
CLIENT_SECRET = os.environ.get("CLIENT_SECRET") # Il Client Secret della tua app

def get_access_token():
    """Ottiene un token temporaneo usando Client ID e Client Secret"""
    auth_url = f"https://{SHOP_URL}/admin/oauth/access_token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    response = requests.post(auth_url, data=payload)
    if response.status_code != 200:
        raise Exception(f"Errore di autenticazione OAuth: {response.text}")
    
    return response.json().get("access_token")

def fetch_all_variants(access_token):
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }
    
    variants_list = []
    has_next_page = True
    end_cursor = None

    while has_next_page:
        cursor_arg = f', after: "{end_cursor}"' if end_cursor else ""
        query = f"""
        {{
          products(first: 50{cursor_arg}) {{
            pageInfo {{
              hasNextPage
              endCursor
            }}
            edges {{
              node {{
                title
                handle
                vendor
                productType
                variants(first: 100) {{
                  edges {{
                    node {{
                      sku
                      title
                      price
                      availableForSale
                      barcode
                      image {{
                        url
                      }}
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        
        response = requests.post(f"https://{SHOP_URL}/admin/api/2024-01/graphql.json", json={"query": query}, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Errore API Shopify: {response.text}")
            
        data = response.json()["data"]["products"]
        
        for product_edge in data["edges"]:
            product = product_edge["node"]
            for variant_edge in product["variants"]["edges"]:
                variant = variant_edge["node"]
                
                variants_list.append({
                    "sku": variant["sku"] or "",
                    "title": f"{product['title']} - {variant['title']}" if variant['title'] != 'Default Title' else product['title'],
                    "url": f"https://{SHOP_URL.replace('.myshopify.com', '')}.com/products/{product['handle']}",
                    "price": variant["price"],
                    "brand": product["vendor"] or "Generico",
                    "availability": "1" if variant["availableForSale"] else "2",
                    "barcode": variant["barcode"] or "",
                    "image": variant["image"]["url"] if variant["image"] else ""
                })

        has_next_page = data["pageInfo"]["hasNextPage"]
        end_cursor = data["pageInfo"]["endCursor"]
        
    return variants_list

def generate_xml(variants):
    root = ET.Element("products")
    
    for v in variants:
        product_elem = ET.SubElement(root, "product")
        
        ET.SubElement(product_elem, "offer_id").text = v["sku"]
        ET.SubElement(product_elem, "title").text = v["title"]
        ET.SubElement(product_elem, "product_url").text = v["url"]
        ET.SubElement(product_elem, "price").text = v["price"]
        ET.SubElement(product_elem, "brand").text = v["brand"]
        ET.SubElement(product_elem, "availability").text = v["availability"]
        ET.SubElement(product_elem, "ean").text = v["barcode"]
        ET.SubElement(product_elem, "image_url").text = v["image"]

    tree = ET.ElementTree(root)
    tree.write("kelkoo.xml", encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    print("Autenticazione in corso...")
    token = get_access_token()
    print("Inizio recupero varianti da Shopify...")
    variants = fetch_all_variants(token)
    print(f"Trovate {len(variants)} varianti. Generazione XML in corso...")
    generate_xml(variants)
    print("File kelkoo.xml generato con successo!")
