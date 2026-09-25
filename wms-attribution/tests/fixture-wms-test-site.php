<?php
/* Test fixture only: emulates the WMS site (affiliate redirect, pages with forms/CTAs). */
// /ibuhanim behaves like a Redirection-plugin 301 to the homepage (no query string).
add_action( 'init', function () {
	$p = trim( parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH ), '/' );
	if ( 'ibuhanim' === $p ) { wp_redirect( home_url( '/' ), 301 ); exit; }
} );
// Every other test page is rendered by this fixture.
add_action( 'template_redirect', function () {
	$p = trim( parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH ), '/' );
	if ( ! in_array( $p, array( '', 'might', 'speakers', 'get-ticket', 'hrd-corp', 'student' ), true ) ) return;
	status_header( 200 );
	?><!doctype html><html><head><meta charset="utf-8"><title>WMS <?php echo esc_html( $p ); ?></title><?php wp_head(); ?></head><body>
	<header><nav class="menu"><a href="/">Home</a> <a href="/speakers">Speakers</a> <a href="/get-ticket">Get Ticket</a> <a href="/contact">Contact</a></nav></header>
	<h1>Page: /<?php echo esc_html( $p ); ?></h1>
	<section id="pricing"><h2>Tickets</h2>
	  <div class="elementor-widget-button"><a class="elementor-button" href="/checkout/?add-to-cart=101">Standard Ticket</a></div>
	  <div class="elementor-widget-button"><a class="elementor-button" href="/checkout/?add-to-cart=102">VIP Ticket</a></div>
	</section>
	<section id="contact"><h2>Contact us</h2>
	  <a id="wa-admin" href="https://wa.me/60123456789?text=Hi%20admin%2C%20saya%20nak%20tanya%20WMS">Contact Admin</a>
	  <a id="wa-sales" href="https://api.whatsapp.com/send?phone=60198765432">Contact Salesperson</a>
	  <a id="wa-float" href="https://wa.me/60123456789"><img alt="WhatsApp" src="data:,"></a>
	  <button id="wa-widget" onclick="window.open('https://wa.me/60111111111?text=Hello','_blank')">Chat</button>
	</section>
	<section id="hrd"><h2>HRD Corp claimable</h2>
	  <form id="hrd-form" name="HRD Corp Form" method="post" action="/thanks">
	    <input name="full_name" value=""> <input name="email" type="email"> <input name="phone" type="tel">
	    <input name="company"> <button type="submit">Submit HRD</button>
	  </form>
	</section>
	<section id="corporate"><h2>Corporate / Bulk</h2>
	  <form class="elementor-form" id="corp-form" method="post"><input type="hidden" name="form_fields[affiliate]" value=""><input name="form_fields[name]"></form>
	</section>
	<section id="ghl"><h2>Student enquiry (GHL)</h2>
	  <iframe id="ghl-frame" src="about:blank" data-src="https://api.leadconnectorhq.com/widget/form/AbC123?notrack=1" style="width:10px;height:10px"></iframe>
	  <a id="ghl-link" href="https://link.msgsndr.com/widget/form/XyZ789">Student enquiry form</a>
	</section>
	<form role="search" id="search"><input name="s"></form>
	<?php wp_footer(); ?></body></html><?php
	exit;
} );
// Emulate a plain HTML form's thank-you target.
add_action( 'template_redirect', function () {
	if ( trim( parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH ), '/' ) === 'thanks' ) { status_header( 200 ); echo 'thanks'; exit; }
}, 0 );
// Test-only: read the conversions table.
add_action( 'rest_api_init', function () {
	register_rest_route( 'wmstest/v1', '/rows', array( 'methods' => 'GET', 'permission_callback' => '__return_true', 'callback' => function () {
		global $wpdb; return $wpdb->get_results( "SELECT * FROM {$wpdb->prefix}wms_conversions ORDER BY id ASC", ARRAY_A );
	} ) );
	register_rest_route( 'wmstest/v1', '/reset', array( 'methods' => 'GET', 'permission_callback' => '__return_true', 'callback' => function () {
		global $wpdb; $wpdb->query( "DELETE FROM {$wpdb->prefix}wms_conversions" ); $wpdb->query( "DELETE FROM {$wpdb->options} WHERE option_name LIKE '_transient%wms_attr_rl_%'" ); return true;
	} ) );
} );

// Test-only: minimal stand-ins for WooCommerce / Elementor objects, to run the plugin's real hooks.
add_action( 'rest_api_init', function () {
	register_rest_route( 'wmstest/v1', '/integrations', array( 'methods' => 'GET', 'permission_callback' => '__return_true', 'callback' => function ( $req ) {
		if ( ! class_exists( 'WC_Order' ) ) {
			eval( 'class WC_Order {
				public $meta = array(); public $id; public $coupons = array(); public $saved = 0;
				function __construct( $id ) { $this->id = $id; }
				function update_meta_data( $k, $v ) { $this->meta[ $k ] = $v; }
				function get_meta( $k ) { return isset( $this->meta[ $k ] ) ? $this->meta[ $k ] : ""; }
				function get_coupon_codes() { return $this->coupons; }
				function save() { $this->saved++; }
				function get_id() { return $this->id; }
				function get_order_number() { return (string) $this->id; }
				function get_total() { return "1500.00"; }
				function get_created_via() { return "checkout"; }
				function get_items() { return array( new WC_Fake_Item() ); }
				function get_billing_first_name() { return "Siti"; } function get_billing_last_name() { return "Buyer"; }
				function get_billing_email() { return "siti@example.com"; } function get_billing_phone() { return "0199998888"; }
				function get_billing_company() { return "Acme Sdn Bhd"; }
				function get_edit_order_url() { return admin_url( "post.php?post=" . $this->id . "&action=edit" ); }
			}
			class WC_Fake_Item { function get_quantity() { return 2; } function get_name() { return "VIP Ticket"; } }
			class Fake_Elementor_Record {
				public $data; function __construct( $f ) { $this->data = array( "fields" => $f ); }
				function get( $k ) { return $this->data[ $k ]; } function set( $k, $v ) { $this->data[ $k ] = $v; }
				function get_form_settings( $k ) { return "Corporate Bulk Form"; }
			}' );
			function wc_get_order( $id ) { return isset( $GLOBALS['wms_test_orders'][ $id ] ) ? $GLOBALS['wms_test_orders'][ $id ] : false; }
		}
		$out = array();

		// WooCommerce checkout → paid (twice, must log once).
		$order = new WC_Order( 1234 );
		if ( $req->get_param( 'coupon' ) ) { $order->coupons = array( $req->get_param( 'coupon' ) ); }
		$GLOBALS['wms_test_orders'][1234] = $order;
		do_action( 'woocommerce_checkout_create_order', $order, array() );
		do_action( 'woocommerce_order_status_processing', 1234 );
		do_action( 'woocommerce_order_status_completed', 1234 );
		$out['order_meta'] = $order->meta;
		ob_start(); WMS_Attr_WooCommerce::render_box( $order ); $out['meta_box'] = wp_strip_all_tags( str_replace( '</tr>', "\n", ob_get_clean() ) );
		ob_start(); WMS_Attr_WooCommerce::column_hpos( 'wms_attr', $order ); $out['orders_column'] = wp_strip_all_tags( str_replace( '<br>', ' | ', ob_get_clean() ) );
		$out['admin_email'] = apply_filters( 'woocommerce_email_order_meta_fields', array(), true, $order );
		$out['customer_email'] = apply_filters( 'woocommerce_email_order_meta_fields', array(), false, $order );

		// Elementor Pro form: enrich (emails/webhooks) + log.
		$rec = new Fake_Elementor_Record( array(
			'name'  => array( 'id' => 'name', 'type' => 'text', 'title' => 'Name', 'value' => 'Encik Korporat' ),
			'email' => array( 'id' => 'email', 'type' => 'email', 'title' => 'Email', 'value' => 'hr@company.my' ),
			'affiliate' => array( 'id' => 'affiliate', 'type' => 'hidden', 'title' => 'Affiliate', 'value' => 'SPOOFED' ),
		) );
		do_action( 'elementor_pro/forms/process', $rec, null );
		do_action( 'elementor_pro/forms/new_record', $rec, null );
		$out['elementor_fields'] = wp_list_pluck( $rec->get( 'fields' ), 'value', 'id' );

		// Contact Form 7 admin mail body.
		$out['cf7_body'] = apply_filters( 'wpcf7_mail_components', array( 'body' => "Name: Ali\nMessage: hi" ) )['body'];
		return $out;
	} ) );
} );
