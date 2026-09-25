<?php
/**
 * WooCommerce: store affiliate / source / campaign / route on every order, show it in admin,
 * add it to the admin order email, and log paid orders as "purchase" conversions.
 */

defined( 'ABSPATH' ) || exit;

class WMS_Attr_WooCommerce {

	/** Order meta key => label. */
	const META = array(
		'_wms_affiliate'    => 'Affiliate',
		'_wms_source'       => 'Source',
		'_wms_medium'       => 'Medium',
		'_wms_campaign'     => 'Campaign',
		'_wms_content'      => 'Content',
		'_wms_term'         => 'Term',
		'_wms_landing_page' => 'Landing page',
		'_wms_referrer'     => 'Referrer',
		'_wms_first_touch'  => 'First touch',
		'_wms_ref'          => 'WMS Ref',
		'_wms_route'        => 'Route',
	);

	const MAP = array(
		'_wms_affiliate'    => 'affiliate',
		'_wms_source'       => 'utm_source',
		'_wms_medium'       => 'utm_medium',
		'_wms_campaign'     => 'utm_campaign',
		'_wms_content'      => 'utm_content',
		'_wms_term'         => 'utm_term',
		'_wms_landing_page' => 'landing_page',
		'_wms_referrer'     => 'referrer',
		'_wms_first_touch'  => 'first_touch',
		'_wms_ref'          => 'wms_ref',
		'_wms_route'        => 'wms_route',
	);

	public static function init() {
		// Save on checkout — classic shortcode checkout and the block checkout.
		add_action( 'woocommerce_checkout_create_order', array( __CLASS__, 'save' ), 10, 1 );
		add_action( 'woocommerce_store_api_checkout_update_order_from_request', array( __CLASS__, 'save' ), 10, 1 );
		// Safety net: thank-you page runs in the buyer's browser, so the cookie is available.
		add_action( 'woocommerce_thankyou', array( __CLASS__, 'fill_missing' ), 5, 1 );
		// Paid → purchase conversion.
		add_action( 'woocommerce_payment_complete', array( __CLASS__, 'log_purchase' ), 20, 1 );
		add_action( 'woocommerce_order_status_processing', array( __CLASS__, 'log_purchase' ), 20, 1 );
		add_action( 'woocommerce_order_status_completed', array( __CLASS__, 'log_purchase' ), 20, 1 );
		// Admin display.
		add_action( 'add_meta_boxes', array( __CLASS__, 'meta_box' ) );
		add_filter( 'manage_edit-shop_order_columns', array( __CLASS__, 'column' ), 20 );
		add_filter( 'manage_woocommerce_page_wc-orders_columns', array( __CLASS__, 'column' ), 20 );
		add_action( 'manage_shop_order_posts_custom_column', array( __CLASS__, 'column_legacy' ), 20, 2 );
		add_action( 'manage_woocommerce_page_wc-orders_custom_column', array( __CLASS__, 'column_hpos' ), 20, 2 );
		// Admin "New order" email.
		add_filter( 'woocommerce_email_order_meta_fields', array( __CLASS__, 'email_fields' ), 10, 3 );
	}

	/** @param WC_Order $order */
	public static function save( $order ) {
		if ( ! is_object( $order ) || ! method_exists( $order, 'update_meta_data' ) ) {
			return;
		}
		$attr = WMS_Attr_Core::current();

		// No affiliate cookie but an affiliate's coupon was used → credit that affiliate.
		if ( '' === $attr['affiliate'] && method_exists( $order, 'get_coupon_codes' ) ) {
			$map = WMS_Attr_Core::affiliates();
			foreach ( (array) $order->get_coupon_codes() as $code ) {
				$slug = WMS_Attr_Core::slug( $code );
				if ( isset( $map[ $slug ] ) ) {
					$attr['affiliate'] = $map[ $slug ] . ' (coupon)';
					break;
				}
			}
		}
		foreach ( self::MAP as $meta => $key ) {
			$order->update_meta_data( $meta, (string) $attr[ $key ] );
		}
	}

	public static function fill_missing( $order_id ) {
		$order = wc_get_order( $order_id );
		if ( $order && '' === (string) $order->get_meta( '_wms_source' ) ) {
			self::save( $order );
			$order->save();
		}
	}

	/** Attribution stored on an order, in WMS_Attr_Core::current() shape. */
	public static function attr_of( $order ) {
		$out = array();
		foreach ( self::MAP as $meta => $key ) {
			$out[ $key ] = (string) $order->get_meta( $meta );
		}
		if ( '' === $out['utm_source'] ) {
			$out['utm_source'] = $order->get_created_via() === 'admin' ? 'manual order' : 'unknown';
		}
		return $out;
	}

	public static function log_purchase( $order_id ) {
		$order = wc_get_order( $order_id );
		if ( ! $order || $order->get_meta( '_wms_logged' ) ) {
			return;
		}
		$items = array();
		foreach ( $order->get_items() as $item ) {
			$items[] = $item->get_quantity() . '× ' . $item->get_name();
		}
		WMS_Attr_Log::add(
			'purchase',
			self::attr_of( $order ),
			array(
				'label'    => 'Order #' . $order->get_order_number() . ( $items ? ' — ' . implode( ', ', $items ) : '' ),
				'page'     => 'checkout',
				'amount'   => (float) $order->get_total(),
				'order_id' => $order->get_id(),
				'contact'  => array(
					'name'    => trim( $order->get_billing_first_name() . ' ' . $order->get_billing_last_name() ),
					'email'   => $order->get_billing_email(),
					'phone'   => $order->get_billing_phone(),
					'company' => $order->get_billing_company(),
				),
			)
		);
		$order->update_meta_data( '_wms_logged', 1 );
		$order->save();
	}

	/* --------------------------------------------------------------- admin */

	public static function meta_box() {
		$screens = array( 'shop_order' );
		if ( function_exists( 'wc_get_page_screen_id' ) ) {
			$screens[] = wc_get_page_screen_id( 'shop-order' );
		}
		foreach ( array_unique( $screens ) as $screen ) {
			add_meta_box( 'wms-attribution', 'WMS Attribution (source)', array( __CLASS__, 'render_box' ), $screen, 'side', 'high' );
		}
	}

	public static function render_box( $post_or_order ) {
		$order = $post_or_order instanceof WC_Order ? $post_or_order : wc_get_order( is_object( $post_or_order ) ? $post_or_order->ID : $post_or_order );
		if ( ! $order ) {
			return;
		}
		$a = self::attr_of( $order );
		echo '<table class="widefat striped" style="border:0"><tbody>';
		foreach ( self::META as $meta => $label ) {
			$v = $a[ self::MAP[ $meta ] ];
			if ( '_wms_ref' === $meta && '' !== $v ) {
				$v = '<a href="' . esc_url( admin_url( 'admin.php?page=wms-attribution&q=' . rawurlencode( $v ) ) ) . '">' . esc_html( $v ) . '</a>';
			} else {
				$v = '' === $v ? '<span style="color:#999">—</span>' : esc_html( $v );
			}
			echo '<tr><th style="width:38%;padding:4px 6px">' . esc_html( $label ) . '</th><td style="padding:4px 6px;word-break:break-word">' . $v . '</td></tr>'; // phpcs:ignore WordPress.Security.EscapeOutput
		}
		echo '</tbody></table>';
	}

	public static function column( $cols ) {
		$out = array();
		foreach ( $cols as $k => $v ) {
			$out[ $k ] = $v;
			if ( 'order_status' === $k ) {
				$out['wms_attr'] = 'Affiliate / Source';
			}
		}
		if ( ! isset( $out['wms_attr'] ) ) {
			$out['wms_attr'] = 'Affiliate / Source';
		}
		return $out;
	}

	public static function column_legacy( $col, $post_id ) {
		if ( 'wms_attr' === $col ) {
			self::column_cell( wc_get_order( $post_id ) );
		}
	}

	public static function column_hpos( $col, $order ) {
		if ( 'wms_attr' === $col ) {
			self::column_cell( $order );
		}
	}

	private static function column_cell( $order ) {
		if ( ! $order ) {
			return;
		}
		$a = self::attr_of( $order );
		echo '<strong>' . esc_html( '' !== $a['affiliate'] ? $a['affiliate'] : '—' ) . '</strong><br><small>' .
			esc_html( $a['utm_source'] . ( '' !== $a['utm_campaign'] ? ' / ' . $a['utm_campaign'] : '' ) ) . '</small>';
	}

	public static function email_fields( $fields, $sent_to_admin, $order ) {
		if ( ! $sent_to_admin || ! is_object( $order ) ) {
			return $fields;
		}
		$a = self::attr_of( $order );
		foreach ( array( '_wms_affiliate', '_wms_source', '_wms_campaign', '_wms_ref', '_wms_route' ) as $meta ) {
			$v = $a[ self::MAP[ $meta ] ];
			if ( '' !== $v ) {
				$fields[ $meta ] = array( 'label' => self::META[ $meta ], 'value' => $v );
			}
		}
		return $fields;
	}
}
