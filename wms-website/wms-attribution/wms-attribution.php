<?php
/**
 * Plugin Name: WMS Attribution
 * Description: One consistent affiliate + source + campaign tracker for every WMS conversion (WooCommerce orders, all forms, GHL forms, WhatsApp, Contact Admin/Salesperson, ticket CTAs). Keeps existing affiliate links (/might, /ibuhanim, ...) working.
 * Version: 1.0.0
 * Author: Annems Leadership Solution Sdn Bhd
 * Requires PHP: 7.4
 * Requires at least: 5.8
 * WC tested up to: 10.2
 * License: GPL-2.0-or-later
 */

defined( 'ABSPATH' ) || exit;

define( 'WMS_ATTR_VERSION', '1.0.0' );
define( 'WMS_ATTR_FILE', __FILE__ );
define( 'WMS_ATTR_DIR', __DIR__ );

require_once WMS_ATTR_DIR . '/includes/class-wms-attr-core.php';
require_once WMS_ATTR_DIR . '/includes/class-wms-attr-log.php';
require_once WMS_ATTR_DIR . '/includes/class-wms-attr-forms.php';
require_once WMS_ATTR_DIR . '/includes/class-wms-attr-woocommerce.php';
require_once WMS_ATTR_DIR . '/includes/class-wms-attr-admin.php';

WMS_Attr_Core::init();
WMS_Attr_Log::init();
WMS_Attr_Forms::init();
WMS_Attr_WooCommerce::init();
WMS_Attr_Admin::init();

register_activation_hook( __FILE__, array( 'WMS_Attr_Log', 'install' ) );

// Declare WooCommerce HPOS (custom order tables) compatibility.
add_action(
	'before_woocommerce_init',
	function () {
		if ( class_exists( '\Automattic\WooCommerce\Utilities\FeaturesUtil' ) ) {
			\Automattic\WooCommerce\Utilities\FeaturesUtil::declare_compatibility( 'custom_order_tables', __FILE__, true );
		}
	}
);
