def add_to_cart(product_id: str, quantity: int, stock_quantity: int, is_vip: bool):
    """
    Xử lý thêm sản phẩm vào giỏ hàng.
    Lưu ý: Có 1 nhánh 'Shadow Logic' ẩn dành cho khách VIP mà Story không nhắc tới!
    """
    if quantity < 1 or quantity > 10:
        return {"status_code": 400, "error": "INVALID_QUANTITY"}

    if stock_quantity <= 0 or quantity > stock_quantity:
        return {"status_code": 422, "error": "OUT_OF_STOCK"}

    # --- SHADOW LOGIC (Nhánh ẩn AST sẽ bắt) ---
    if is_vip and quantity >= 5:
        vip_gift = "FREE_GIFT_CUP"
    else:
        vip_gift = None

    return {
        "status_code": 200,
        "message": "ADDED_SUCCESS",
        "product_id": product_id,
        "quantity": quantity,
        "gift": vip_gift,
    }
