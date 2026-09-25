<?php
/**
 * Settings, the wms_attr cookie, server-side capture of affiliate links, and the front-end script.
 *
 * Cookie format (JSON, shared with assets/wms-attribution.js):
 *   v  visitor reference (WMS-XXXXXX)      t  first visit (unix)
 *   a  affiliate code (might)              an affiliate display name (MIGHT)     at affiliate time
 *   s/m/c/n/k  utm source/medium/campaign/content/term (last non-direct touch)
 *   lp landing page of that touch          r0 referrer domain                    st touch time
 *   f  first touch {a,s,c,l,t}             r  route: last pages, '*' = new arrival
 */

defined( 'ABSPATH' ) || exit;

class WMS_Attr_Core {

	const COOKIE = 'wms_attr';
	const OPTION = 'wms_attr_settings';

	/** Existing WMS affiliate / reseller links. Editable in WMS Attribution → Settings. */
	const DEFAULT_AFFILIATES = "might | MIGHT\nibuhanim | Ibu Hanim\nannems | Annems\npeoplelogy | Peoplelogy\nlincgroup | Linc Group";

	/** Query parameters that carry an affiliate code (?ref=might). */
	const AFF_PARAMS = array( 'ref', 'aff', 'affiliate', 'affid', 'reseller' );

	private static $data = null;

	public static function init() {
		// Early, before redirect plugins (Redirection, Pretty Links, Elementor) send /might elsewhere.
		add_action( 'plugins_loaded', array( __CLASS__, 'capture_arrival' ), 1 );
		add_action( 'wp_enqueue_scripts', array( __CLASS__, 'enqueue' ), 5 );
	}

	/* ------------------------------------------------------------ settings */

	public static function settings() {
		$s = get_option( self::OPTION, array() );
		return wp_parse_args(
			is_array( $s ) ? $s : array(),
			array(
				'affiliates'    => self::DEFAULT_AFFILIATES,
				'days'          => 90,
				'wa_ref'        => 1,
				'ghl_hosts'     => '',
				'cookie_domain' => '',
			)
		);
	}

	/** @return array slug => display name */
	public static function affiliates() {
		$out = array();
		foreach ( preg_split( '/\r\n|\r|\n/', (string) self::settings()['affiliates'] ) as $line ) {
			$parts = array_map( 'trim', explode( '|', $line, 2 ) );
			$slug  = self::slug( $parts[0] );
			if ( '' !== $slug ) {
				$out[ $slug ] = ( isset( $parts[1] ) && '' !== $parts[1] ) ? $parts[1] : strtoupper( $slug );
			}
		}
		return $out;
	}

	public static function affiliate_name( $slug ) {
		$map = self::affiliates();
		return isset( $map[ $slug ] ) ? $map[ $slug ] : strtoupper( $slug );
	}

	public static function slug( $s ) {
		return substr( preg_replace( '/[^a-z0-9_-]+/', '', strtolower( trim( (string) $s ) ) ), 0, 60 );
	}

	private static function clip( $s, $n ) {
		$s = trim( wp_strip_all_tags( (string) $s ) );
		return function_exists( 'mb_substr' ) ? mb_substr( $s, 0, $n ) : substr( $s, 0, $n );
	}

	/* -------------------------------------------------------------- cookie */

	/** Raw cookie data (see format above). */
	public static function raw() {
		if ( null === self::$data ) {
			self::$data = array();
			if ( ! empty( $_COOKIE[ self::COOKIE ] ) ) {
				$d = json_decode( wp_unslash( $_COOKIE[ self::COOKIE ] ), true ); // phpcs:ignore WordPress.Security.ValidatedSanitizedInput
				if ( is_array( $d ) ) {
					self::$data = $d;
				}
			}
		}
		return self::$data;
	}

	private static function write( array $d ) {
		self::$data = $d;
		if ( headers_sent() ) {
			return;
		}
		$s       = self::settings();
		$expires = time() + DAY_IN_SECONDS * max( 1, (int) $s['days'] );
		// Raw cookie so JavaScript's decodeURIComponent() reads it back exactly.
		setrawcookie(
			self::COOKIE,
			rawurlencode( wp_json_encode( $d, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE ) ),
			array(
				'expires'  => $expires,
				'path'     => '/',
				'domain'   => (string) $s['cookie_domain'],
				'secure'   => is_ssl(),
				'httponly' => false,
				'samesite' => 'Lax',
			)
		);
		$_COOKIE[ self::COOKIE ] = wp_json_encode( $d, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE );
	}

	/**
	 * Flat attribution for the current visitor — the same keys the forms, GHL and the log use.
	 * Posted hidden fields (from the browser) fill gaps when the cookie is unavailable.
	 */
	public static function current( array $posted = array() ) {
		$d   = self::raw();
		$get = function ( $k ) use ( $posted ) {
			return isset( $posted[ $k ] ) && is_scalar( $posted[ $k ] ) ? self::clip( $posted[ $k ], 300 ) : '';
		};

		$aff_code = isset( $d['a'] ) ? self::slug( $d['a'] ) : '';
		$aff_name = $aff_code ? ( isset( $d['an'] ) ? self::clip( $d['an'], 80 ) : self::affiliate_name( $aff_code ) ) : $get( 'affiliate' );

		// Fall back to an existing affiliate plugin's cookie, if the site has one.
		if ( '' === $aff_name ) {
			foreach ( array( 'affwp_ref' => 'AffiliateWP #', 'slicewp_aff' => 'SliceWP #', 'wpam_id' => 'Affiliate #' ) as $c => $prefix ) {
				if ( ! empty( $_COOKIE[ $c ] ) ) {
					$aff_name = $prefix . self::clip( wp_unslash( $_COOKIE[ $c ] ), 20 ); // phpcs:ignore
					break;
				}
			}
		}

		$route = isset( $d['r'] ) && is_array( $d['r'] ) ? implode( ' > ', array_map( 'strval', $d['r'] ) ) : $get( 'wms_route' );
		$first = '';
		if ( isset( $d['f'] ) && is_array( $d['f'] ) ) {
			$f     = $d['f'];
			$first = implode(
				' / ',
				array_filter(
					array(
						! empty( $f['a'] ) ? self::affiliate_name( self::slug( $f['a'] ) ) : '',
						isset( $f['s'] ) ? $f['s'] : '',
						isset( $f['c'] ) ? $f['c'] : '',
					)
				)
			);
		}

		$src = isset( $d['s'] ) && '' !== $d['s'] ? $d['s'] : $get( 'utm_source' );

		return array(
			'affiliate'      => $aff_name,
			'affiliate_code' => $aff_code,
			'utm_source'     => self::clip( '' !== $src ? $src : 'direct', 100 ), // never empty
			'utm_medium'     => self::clip( isset( $d['m'] ) ? $d['m'] : $get( 'utm_medium' ), 100 ),
			'utm_campaign'   => self::clip( isset( $d['c'] ) ? $d['c'] : $get( 'utm_campaign' ), 150 ),
			'utm_content'    => self::clip( isset( $d['n'] ) ? $d['n'] : $get( 'utm_content' ), 150 ),
			'utm_term'       => self::clip( isset( $d['k'] ) ? $d['k'] : $get( 'utm_term' ), 100 ),
			'landing_page'   => self::clip( isset( $d['lp'] ) ? $d['lp'] : $get( 'landing_page' ), 200 ),
			'referrer'       => self::clip( isset( $d['r0'] ) ? $d['r0'] : $get( 'referrer' ), 100 ),
			'wms_ref'        => self::clip( isset( $d['v'] ) ? $d['v'] : $get( 'wms_ref' ), 20 ),
			'wms_route'      => self::clip( $route, 1000 ),
			'first_touch'    => self::clip( '' !== $first ? $first : $get( 'first_touch' ), 200 ),
		);
	}

	/* -------------------------------------------------- server-side capture */

	/**
	 * Record affiliate links and UTM on arrival, before any redirect.
	 * Needed because /might is often a redirect: the browser never sees "/might" in JavaScript.
	 */
	public static function capture_arrival() {
		if ( is_admin() || wp_doing_ajax() || wp_doing_cron() || ( defined( 'REST_REQUEST' ) && REST_REQUEST ) ) {
			return;
		}
		if ( empty( $_SERVER['REQUEST_METHOD'] ) || 'GET' !== $_SERVER['REQUEST_METHOD'] || empty( $_SERVER['REQUEST_URI'] ) ) {
			return;
		}
		$uri  = wp_unslash( $_SERVER['REQUEST_URI'] ); // phpcs:ignore WordPress.Security.ValidatedSanitizedInput
		$path = (string) wp_parse_url( $uri, PHP_URL_PATH );
		if ( preg_match( '#^/(wp-json|wp-content|wp-includes|wp-admin)/|\.(js|css|png|jpe?g|gif|svg|webp|ico|woff2?|map|xml|txt)$#i', $path ) ) {
			return;
		}

		// Affiliate: ?ref=/aff= value, or first path segment listed in settings (/might).
		$aff = '';
		foreach ( self::AFF_PARAMS as $p ) {
			if ( ! empty( $_GET[ $p ] ) && is_string( $_GET[ $p ] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
				$aff = self::slug( wp_unslash( $_GET[ $p ] ) ); // phpcs:ignore
				if ( $aff ) {
					break;
				}
			}
		}
		if ( ! $aff ) {
			$home_path = trim( (string) wp_parse_url( home_url( '/' ), PHP_URL_PATH ), '/' );
			$rel       = trim( $path, '/' );
			if ( '' !== $home_path && 0 === strpos( $rel, $home_path ) ) {
				$rel = trim( substr( $rel, strlen( $home_path ) ), '/' );
			}
			$first = self::slug( strtok( $rel, '/' ) );
			if ( $first && array_key_exists( $first, self::affiliates() ) ) {
				$aff = $first;
			}
		}

		$utm = array();
		foreach ( array( 's' => 'utm_source', 'm' => 'utm_medium', 'c' => 'utm_campaign', 'n' => 'utm_content', 'k' => 'utm_term' ) as $k => $p ) {
			$utm[ $k ] = isset( $_GET[ $p ] ) && is_string( $_GET[ $p ] ) ? self::clip( wp_unslash( $_GET[ $p ] ), 150 ) : ''; // phpcs:ignore
		}
		$has_utm = '' !== $utm['s'] || '' !== $utm['c'] || '' !== $utm['m'];

		if ( ! $aff && ! $has_utm ) {
			return; // Nothing new; the browser script handles referrers and direct visits.
		}

		$d = self::raw();
		$t = time();
		if ( empty( $d['v'] ) ) {
			$d['v'] = self::new_ref();
		}
		if ( empty( $d['t'] ) ) {
			$d['t'] = $t;
		}
		if ( $aff ) {
			$d['a']  = $aff;
			$d['an'] = self::affiliate_name( $aff );
			$d['at'] = $t;
		}

		$ref_host = '';
		if ( ! empty( $_SERVER['HTTP_REFERER'] ) ) {
			$ref_host = preg_replace( '/^www\./', '', (string) wp_parse_url( wp_unslash( $_SERVER['HTTP_REFERER'] ), PHP_URL_HOST ) ); // phpcs:ignore
			$own      = preg_replace( '/^www\./', '', (string) wp_parse_url( home_url(), PHP_URL_HOST ) );
			if ( $ref_host === $own ) {
				$ref_host = '';
			}
		}

		if ( $has_utm ) {
			$touch = array(
				's' => '' !== $utm['s'] ? $utm['s'] : ( $ref_host ? self::classify_referrer( $ref_host )[0] : 'affiliate' ),
				'm' => $utm['m'],
				'c' => $utm['c'],
				'n' => $utm['n'],
				'k' => $utm['k'],
			);
		} elseif ( $ref_host ) {
			$cr    = self::classify_referrer( $ref_host );
			$touch = array( 's' => $cr[0], 'm' => $cr[1], 'c' => '', 'n' => '', 'k' => '' );
		} else {
			$touch = array( 's' => 'affiliate', 'm' => 'affiliate_link', 'c' => '', 'n' => '', 'k' => '' );
		}
		$d        = array_merge( $d, $touch );
		$d['lp']  = self::clip( $uri, 200 );
		$d['r0']  = self::clip( $ref_host, 80 );
		$d['st']  = $t;
		$d['ss']  = 1; // tells the browser script this arrival is already recorded
		if ( empty( $d['f'] ) ) {
			$d['f'] = array( 'a' => isset( $d['a'] ) ? $d['a'] : '', 's' => $d['s'], 'c' => $d['c'], 'l' => $d['lp'], 't' => $d['t'] );
		}
		$r   = isset( $d['r'] ) && is_array( $d['r'] ) ? $d['r'] : array();
		$mark = '*' . self::clip( '' !== $path ? $path : '/', 80 );
		if ( end( $r ) !== $mark ) {
			$r[] = $mark;
		}
		$d['r'] = array_slice( $r, -15 );

		self::write( $d );
		if ( ! headers_sent() ) {
			nocache_headers(); // don't let a page cache store this visitor's cookie
		}
	}

	public static function classify_referrer( $host ) {
		$rules = array(
			'/(^|\.)google\./'                                => array( 'google', 'organic' ),
			'/(^|\.)bing\.com$/'                               => array( 'bing', 'organic' ),
			'/(^|\.)(facebook\.com|fb\.com|fb\.me)$/'          => array( 'facebook', 'social' ),
			'/(^|\.)instagram\.com$/'                          => array( 'instagram', 'social' ),
			'/(^|\.)(linkedin\.com|lnkd\.in)$/'                => array( 'linkedin', 'social' ),
			'/(^|\.)(t\.co|twitter\.com|x\.com)$/'             => array( 'x', 'social' ),
			'/(^|\.)tiktok\.com$/'                             => array( 'tiktok', 'social' ),
			'/(^|\.)(youtube\.com|youtu\.be)$/'                => array( 'youtube', 'social' ),
		);
		foreach ( $rules as $re => $v ) {
			if ( preg_match( $re, $host ) ) {
				return $v;
			}
		}
		return array( $host, 'referral' );
	}

	public static function new_ref() {
		$chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
		$out   = '';
		for ( $i = 0; $i < 6; $i++ ) {
			$out .= $chars[ random_int( 0, strlen( $chars ) - 1 ) ];
		}
		return 'WMS-' . $out;
	}

	/* ---------------------------------------------------------- front-end */

	public static function enqueue() {
		$s = self::settings();
		wp_enqueue_script(
			'wms-attribution',
			plugins_url( 'assets/wms-attribution.js', WMS_ATTR_FILE ),
			array(),
			WMS_ATTR_VERSION,
			array( 'in_footer' => false ) // in <head>: the cookie must exist before forms and chat widgets load
		);
		$home_host = preg_replace( '/^www\./', '', (string) wp_parse_url( home_url(), PHP_URL_HOST ) );
		wp_localize_script(
			'wms-attribution',
			'WMS_ATTR_CFG',
			array(
				'endpoint'     => esc_url_raw( rest_url( 'wms/v1/event' ) ),
				'cookie'       => self::COOKIE,
				'days'         => (int) $s['days'],
				'cookieDomain' => (string) $s['cookie_domain'],
				'affiliates'   => (object) self::affiliates(),
				'affParams'    => self::AFF_PARAMS,
				'waRef'        => (bool) $s['wa_ref'],
				'ghlHosts'     => array_values( array_filter( array_map( 'trim', preg_split( '/[\s,]+/', (string) $s['ghl_hosts'] ) ) ) ),
				'siteHosts'    => array( $home_host ),
			)
		);
	}
}
