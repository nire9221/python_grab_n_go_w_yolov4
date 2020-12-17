import cx_Oracle
import os



os.putenv('NLS_LANG', '.UTF8')

#연결에 필요한 기본 정보 (유저, 비밀번호, 데이터베이스 서버 주소)
connection = cx_Oracle.connect("Ai_team1","1234","192.168.0.12:1521/orcl")
cursor = connection.cursor()
connection.autocommit = True


# cursor.execute("""
#    select customer_id, customer_name
#    from CUSTOMERS
#    """
# )
# for name in cursor:
#    print("테스트 이름 리스트 : ", name)


def get_loggedincustomer (): 
   sql="select customer_id, customer_name from customers where login_session = 'True'"
   cursor.execute(sql)
   for ids in cursor:
      print("logged in customer info : ", ids)
# get_loggedincustomer()


def get_product_info (item):
   # sql = "select * from products where product_name = %s"
   cursor.execute("select * from products where product_name = :name", {"name": item})
   for items in cursor:
      print("product info : ", items)
# get_product_info('banana')

######################################
'''
카트에 들어가야할 상황 
- track id 가 존재하지 않는경우 (한 track id 에 아무런 class_name 기록이 존재하지 않는경우)

카트를 업데이트해야할 상황 
- db에 해당 track id 와 product id (class_name)이 존재하지만 qty가 변경된 경우
- db에 track id 와 class_name이 존재하지만 다른 이름의 class name 이 추가된경우

카트내용을 삭제해야할 상황 
- 한 track id 에 모든 class_name의 qty 가 0인경우
'''

def add_to_cart(track_id,class_name,counted_class):
   #update customers set login_session = 'False' where customer_id = :id", {"id": customer_id})
   cursor.execute("INSERT INTO carts (cart_id,customer_id,product_id,cart_stock,cart_in) VALUES (cart_seq.nextval,(SELECT customer_id FROM customers WHERE customer_id = :customer_id),(SELECT product_id FROM products WHERE product_name = :product_name),:qty, sysdate)",{"customer_id":track_id, "product_name":class_name, "qty":counted_class})
   
# addToCart(4,"banana",3)

# def update_cart(track_id,class_name,counted_class):
#    # update if cart_stock > 0
#       cursor.execute("UPDATE FROM carts WHERE customer_id = :customer_id SET product_id.product_name = :product_id",{"customer_id": track_id, "product_name":class_name, "qty":counted_class.values()})
#    # else : # cart_stock < 0
#       cursor.execute("DELETE FROM carts WHERE customer_id = :customer_id",{"customer_id":track_id, "product_name":class_name, "qty":counted_class.values()})

# def delete_cart(customer_id):
#    cursor.execute("delete carts where customer_id = :id", {"id": customer_id})

# def update_cart(track_id,class_name,counted_class):
#    cursor.execute("SELECT *,(CASE WHEN NOT EXISTS (SELECT cart_id FROM carts WHERE customer_id=:customer_id) THEN add_to_cart(:customer_id,:product_name,:qty) WHEN NOT EXISTS (SELECT products.product_name FROM carts INNER JOIN products ON carts.product_id=products.product_id WHERE products.product_name=:product_name) THEN add_to_cart(:customer_id,:product_name,:qty) WHEN cart_stock <=0 THEN delete_cart(:customer_id,:product_name,:qty) ELSE 'Not Found' END;) FROM carts",{"customer_id":track_id, "product_name":class_name, "qty":counted_class})

# update_cart(4,"apple",3)

