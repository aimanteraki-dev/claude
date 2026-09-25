<?php
/**
 * One table for every conversion: purchases, form submissions, GHL forms, WhatsApp and CTA clicks.
 * Browser events arrive at POST /wp-json/wms/v1/event.
 */

defined( 'ABSPATH' ) || exit;

class WMS_Attr_Log {

	const DB_VERSION = '1';

	/** Event types that browsers may report. Purchases and server-side form entries are logged by PHP only. */
	const CLIENT_TYPES = array( 'whatsapp', 'call', 'email', 'cta_click', 'add_to_cart', 'form_submit', 'ghl_form' );

	public static function init() {
		add_action( 'init', array( __CLASS__, 'maybe_install' ) );
		add_action( 'rest_api_init', array( __CLASS__, 'register_route' ) );
	}

	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'wms_conversions';
	}

	public static function install() {
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		$t = self::table();
		dbDelta(
			"CREATE TABLE $t (
				id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
				created_at datetime NOT NULL,
				type varchar(30) NOT NULL DEFAULT '',
				label varchar(191) NOT NULL DEFAULT '',
				location varchar(191) NOT NULL DEFAULT '',
				page varchar(255) NOT NULL DEFAULT '',
				affiliate varchar(100) NOT NULL DEFAULT '',
				source varchar(100) NOT NULL DEFAULT '',
				medium varchar(100) NOT NULL DEFAULT '',
				campaign varchar(150) NOT NULL DEFAULT '',
				content varchar(150) NOT NULL DEFAULT '',
				term varchar(100) NOT NULL DEFAULT '',
				landing_page varchar(255) NOT NULL DEFAULT '',
				referrer varchar(100) NOT NULL DEFAULT '',
				first_touch varchar(200) NOT NULL DEFAULT '',
				visitor_ref varchar(20) NOT NULL DEFAULT '',
				route text NULL,
				contact_name varchar(150) NOT NULL DEFAULT '',
				contact_email varchar(150) NOT NULL DEFAULT '',
				contact_phone varchar(50) NOT NULL DEFAULT '',
				amount decimal(12,2) NULL,
				order_id bigint(20) unsigned NULL,
				extra text NULL,
				PRIMARY KEY  (id),
				KEY created_at (created_at),
				KEY type (type),
				KEY affiliate (affiliate),
				KEY visitor_ref (visitor_ref)
			) {$wpdb->get_charset_collate()};"
		);
		update_option( 'wms_attr_db_version', self::DB_VERSION );
	}

	public static function maybe_install() {
		if ( get_option( 'wms_attr_db_version' ) !== self::DB_VERSION ) {
			self::install();
		}
	}

	/**
	 * Insert one conversion.
	 *
	 * @param string $type    purchase|form_submit|ghl_form|whatsapp|call|email|cta_click|add_to_cart
	 * @param array  $attr    WMS_Attr_Core::current() shape
	 * @param array  $extra   label, location, page, contact(name,email,phone,company), amount, order_id, target
	 */
	public static function add( $type, array $attr, array $extra = array() ) {
		global $wpdb;
		$c   = isset( $extra['contact'] ) && is_array( $extra['contact'] ) ? $extra['contact'] : array();
		$cut = function ( $v, $n ) {
			$v = trim( wp_strip_all_tags( is_scalar( $v ) ? (string) $v : '' ) );
			return function_exists( 'mb_substr' ) ? mb_substr( $v, 0, $n ) : substr( $v, 0, $n );
		};
		$get = function ( $a, $k ) {
			return isset( $a[ $k ] ) ? $a[ $k ] : '';
		};
		$other = array_filter(
			array(
				'target'  => $cut( $get( $extra, 'target' ), 200 ),
				'company' => $cut( $get( $c, 'company' ), 150 ),
			)
		);
		$row = array(
			'created_at'    => current_time( 'mysql', true ),
			'type'          => $cut( $type, 30 ),
			'label'         => $cut( $get( $extra, 'label' ), 191 ),
			'location'      => $cut( $get( $extra, 'location' ), 191 ),
			'page'          => $cut( $get( $extra, 'page' ), 255 ),
			'affiliate'     => $cut( $get( $attr, 'affiliate' ), 100 ),
			'source'        => $cut( '' !== $get( $attr, 'utm_source' ) ? $attr['utm_source'] : 'direct', 100 ),
			'medium'        => $cut( $get( $attr, 'utm_medium' ), 100 ),
			'campaign'      => $cut( $get( $attr, 'utm_campaign' ), 150 ),
			'content'       => $cut( $get( $attr, 'utm_content' ), 150 ),
			'term'          => $cut( $get( $attr, 'utm_term' ), 100 ),
			'landing_page'  => $cut( $get( $attr, 'landing_page' ), 255 ),
			'referrer'      => $cut( $get( $attr, 'referrer' ), 100 ),
			'first_touch'   => $cut( $get( $attr, 'first_touch' ), 200 ),
			'visitor_ref'   => $cut( $get( $attr, 'wms_ref' ), 20 ),
			'route'         => $cut( $get( $attr, 'wms_route' ), 1000 ),
			'contact_name'  => $cut( $get( $c, 'name' ), 150 ),
			'contact_email' => $cut( $get( $c, 'email' ), 150 ),
			'contact_phone' => $cut( $get( $c, 'phone' ), 50 ),
			'amount'        => isset( $extra['amount'] ) && is_numeric( $extra['amount'] ) ? (float) $extra['amount'] : null,
			'order_id'      => ! empty( $extra['order_id'] ) ? absint( $extra['order_id'] ) : null,
			'extra'         => $other ? wp_json_encode( $other ) : null,
		);
		$wpdb->insert( self::table(), $row ); // phpcs:ignore WordPress.DB.DirectDatabaseQuery
		do_action( 'wms_attr_logged', $type, $row );
		return (int) $wpdb->insert_id;
	}

	/* ----------------------------------------------------------------- REST */

	public static function register_route() {
		register_rest_route(
			'wms/v1',
			'/event',
			array(
				'methods'             => 'POST',
				'callback'            => array( __CLASS__, 'rest_event' ),
				'permission_callback' => '__return_true', // public: page caches make nonces unreliable; input is length-capped and throttled
			)
		);
	}

	public static function rest_event( WP_REST_Request $req ) {
		$body = $req->get_body();
		if ( strlen( $body ) > 8000 ) {
			return new WP_REST_Response( array( 'ok' => false ), 413 );
		}
		$p = json_decode( $body, true );
		if ( ! is_array( $p ) || empty( $p['type'] ) || ! in_array( $p['type'], self::CLIENT_TYPES, true ) ) {
			return new WP_REST_Response( array( 'ok' => false ), 400 );
		}

		// Light throttle: 60 events per minute per IP.
		$ip  = isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : '';
		$key = 'wms_attr_rl_' . md5( $ip );
		$n   = (int) get_transient( $key );
		if ( $n >= 60 ) {
			return new WP_REST_Response( array( 'ok' => false ), 429 );
		}
		set_transient( $key, $n + 1, MINUTE_IN_SECONDS );

		// Cookie is authoritative; the posted copy fills gaps (e.g. cookie blocked).
		$attr = WMS_Attr_Core::current( $p );
		$id   = self::add(
			$p['type'],
			$attr,
			array(
				'label'    => isset( $p['label'] ) ? $p['label'] : '',
				'location' => isset( $p['location'] ) ? $p['location'] : '',
				'page'     => isset( $p['page'] ) ? $p['page'] : '',
				'target'   => isset( $p['target'] ) ? $p['target'] : '',
				'contact'  => isset( $p['contact'] ) && is_array( $p['contact'] ) ? $p['contact'] : array(),
			)
		);
		return new WP_REST_Response( array( 'ok' => true, 'id' => $id ), 200 );
	}

	/* ---------------------------------------------------------------- query */

	/**
	 * @param array $f type, affiliate, source, q (search), from, to (Y-m-d), limit, offset
	 */
	public static function query( array $f, $count_only = false ) {
		global $wpdb;
		$t     = self::table();
		$where = array( '1=1' );
		$args  = array();
		foreach ( array( 'type', 'affiliate', 'source' ) as $k ) {
			if ( isset( $f[ $k ] ) && '' !== $f[ $k ] ) {
				$where[] = "$k = %s";
				$args[]  = $f[ $k ];
			}
		}
		if ( ! empty( $f['from'] ) ) {
			$where[] = 'created_at >= %s';
			$args[]  = get_gmt_from_date( $f['from'] . ' 00:00:00' );
		}
		if ( ! empty( $f['to'] ) ) {
			$where[] = 'created_at <= %s';
			$args[]  = get_gmt_from_date( $f['to'] . ' 23:59:59' );
		}
		if ( ! empty( $f['q'] ) ) {
			$like    = '%' . $wpdb->esc_like( $f['q'] ) . '%';
			$where[] = '(visitor_ref LIKE %s OR contact_email LIKE %s OR contact_phone LIKE %s OR contact_name LIKE %s OR label LIKE %s OR campaign LIKE %s OR order_id = %d)';
			array_push( $args, $like, $like, $like, $like, $like, $like, absint( $f['q'] ) );
		}
		$sql_where = implode( ' AND ', $where );
		if ( $count_only ) {
			$sql = "SELECT COUNT(*) FROM $t WHERE $sql_where";
			return (int) $wpdb->get_var( $args ? $wpdb->prepare( $sql, $args ) : $sql ); // phpcs:ignore
		}
		$limit  = isset( $f['limit'] ) ? max( 1, (int) $f['limit'] ) : 50;
		$offset = isset( $f['offset'] ) ? max( 0, (int) $f['offset'] ) : 0;
		$sql    = "SELECT * FROM $t WHERE $sql_where ORDER BY id DESC LIMIT $limit OFFSET $offset";
		return $wpdb->get_results( $args ? $wpdb->prepare( $sql, $args ) : $sql, ARRAY_A ); // phpcs:ignore
	}

	/** Conversions per affiliate/source and type over a date range. */
	public static function summary( $from, $to ) {
		global $wpdb;
		$t = self::table();
		return $wpdb->get_results( // phpcs:ignore
			$wpdb->prepare(
				"SELECT IF(affiliate = '', '(no affiliate)', affiliate) AS affiliate, source, type, COUNT(*) AS n, SUM(COALESCE(amount,0)) AS revenue
				 FROM $t WHERE created_at BETWEEN %s AND %s
				 GROUP BY 1, source, type ORDER BY 1, source, type",
				get_gmt_from_date( $from . ' 00:00:00' ),
				get_gmt_from_date( $to . ' 23:59:59' )
			),
			ARRAY_A
		);
	}

	public static function distinct( $col ) {
		global $wpdb;
		if ( ! in_array( $col, array( 'type', 'affiliate', 'source' ), true ) ) {
			return array();
		}
		$t = self::table();
		return $wpdb->get_col( "SELECT DISTINCT $col FROM $t WHERE $col <> '' ORDER BY $col LIMIT 200" ); // phpcs:ignore
	}
}
