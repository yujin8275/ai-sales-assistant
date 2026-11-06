
-- ABC Electronics
-- PostgreSQL 18 / Database: ai_sales
-- RDB 테이블 10개 생성
-- 기존 테이블이 없는 상태에서 실행

BEGIN;

-- 1. 상품 카테고리
CREATE TABLE public.categories (
    category_id   VARCHAR(20) PRIMARY KEY,
    category_name VARCHAR(50) NOT NULL UNIQUE
);

-- 2. 상품 기본정보
CREATE TABLE public.products (
    product_id         VARCHAR(40) PRIMARY KEY,
    category_id        VARCHAR(20) NOT NULL
        REFERENCES public.categories(category_id),
    product_name       VARCHAR(100) NOT NULL,
    brand              VARCHAR(50) NOT NULL,
    product_tier       VARCHAR(20),
    release_date       DATE,
    product_image_path TEXT
);

-- 3. 상품 옵션 (외부 SKU 사용)
CREATE TABLE public.product_variants (
    sku              VARCHAR(64) PRIMARY KEY,
    product_id       VARCHAR(40) NOT NULL
        REFERENCES public.products(product_id),
    color            VARCHAR(30),
    ram_capacity     INTEGER CHECK (ram_capacity > 0),
    storage_capacity INTEGER CHECK (storage_capacity > 0)
);

-- 4. 제품 공통 사양
CREATE TABLE public.product_specs (
    product_id       VARCHAR(40) PRIMARY KEY
        REFERENCES public.products(product_id),
    processor        VARCHAR(100),
    thickness        NUMERIC(6,2) CHECK (thickness > 0),
    width            NUMERIC(6,2) CHECK (width > 0),
    height           NUMERIC(6,2) CHECK (height > 0),
    weight           INTEGER CHECK (weight > 0),
    battery_capacity INTEGER CHECK (battery_capacity > 0)
);

-- 5. 디스플레이 사양
CREATE TABLE public.display_specs (
    product_id         VARCHAR(40) PRIMARY KEY
        REFERENCES public.products(product_id),
    display_panel      VARCHAR(50),
    display_size       NUMERIC(4,2) CHECK (display_size > 0),
    display_brightness INTEGER CHECK (display_brightness > 0)
);

-- 6. 카메라 사양
CREATE TABLE public.cameras (
    camera_id     VARCHAR(40) PRIMARY KEY,
    product_id    VARCHAR(40) NOT NULL
        REFERENCES public.products(product_id),
    camera_type   VARCHAR(30),
    resolution_mp NUMERIC(6,2) CHECK (resolution_mp >= 0),
    aperture      VARCHAR(20),
    max_zoom      NUMERIC(6,2) CHECK (max_zoom >= 0),
    ois           BOOLEAN
);

-- 7. 가격 및 재고
CREATE TABLE public.inventory_prices (
    sku            VARCHAR(64) PRIMARY KEY
        REFERENCES public.product_variants(sku),
    list_price     BIGINT NOT NULL CHECK (list_price > 0),
    sale_price     BIGINT NOT NULL
        CHECK (sale_price >= 0 AND sale_price <= list_price),
    stock_quantity INTEGER NOT NULL DEFAULT 0
        CHECK (stock_quantity >= 0),
    updated_at     TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);

-- 가격·재고 수정 시 updated_at 자동 갱신
CREATE OR REPLACE FUNCTION
    public.touch_inventory_prices_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_inventory_prices_updated_at
BEFORE UPDATE ON public.inventory_prices
FOR EACH ROW
EXECUTE FUNCTION
    public.touch_inventory_prices_updated_at();

-- 8. 최근 3개월 판매량
CREATE TABLE public.sku_sales (
    sku                  VARCHAR(64) PRIMARY KEY
        REFERENCES public.product_variants(sku),
    sales_quantity_3m    INTEGER NOT NULL DEFAULT 0
        CHECK (sales_quantity_3m >= 0),
    sales_reference_date DATE NOT NULL
);

-- 9. 카드 할인 정책
CREATE TABLE public.card_promotions (
    promotion_id   VARCHAR(40) PRIMARY KEY,
    card_company   VARCHAR(50) NOT NULL,
    discount_rate  NUMERIC(5,2) NOT NULL
        CHECK (discount_rate BETWEEN 0 AND 100),
    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL,
    applies_to_all BOOLEAN NOT NULL DEFAULT FALSE,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT chk_card_promo_date_order
        CHECK (end_date >= start_date)
);

-- 10. 카드 할인 적용 상품
CREATE TABLE public.promotion_products (
    promotion_id VARCHAR(40) NOT NULL
        REFERENCES public.card_promotions(promotion_id),
    product_id   VARCHAR(40) NOT NULL
        REFERENCES public.products(product_id),

    PRIMARY KEY (promotion_id, product_id)
);

-- 조회 성능을 위한 인덱스
CREATE INDEX idx_products_category_brand
    ON public.products(category_id, brand);

CREATE INDEX idx_variants_product_id
    ON public.product_variants(product_id);

CREATE INDEX idx_cameras_product_id
    ON public.cameras(product_id);

CREATE INDEX idx_inventory_sale_price
    ON public.inventory_prices(sale_price);

CREATE INDEX idx_promotion_products_product_id
    ON public.promotion_products(product_id);

COMMIT;
