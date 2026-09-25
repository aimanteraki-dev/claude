<?php
/**
 * WP Admin → WMS Attribution: conversions list (with visitor journey), summary by affiliate, CSV, settings.
 */

defined( 'ABSPATH' ) || exit;

class WMS_Attr_Admin {

	const CAP = 'manage_woocommerce';

	const TYPE_LABELS = array(
		'purchase'    => 'Purchase',
		'form_submit' => 'Form',
		'ghl_form'    => 'GHL form',
		'whatsapp'    => 'WhatsApp',
		'call'        => 'Call',
		'email'       => 'Email',
		'cta_click'   => 'CTA click',
		'add_to_cart' => 'Add to cart',
	);

	public static function init() {
		add_action( 'admin_menu', array( __CLASS__, 'menu' ) );
		add_action( 'admin_post_wms_attr_csv', array( __CLASS__, 'csv' ) );
		add_action( 'admin_post_wms_attr_save', array( __CLASS__, 'save_settings' ) );
	}

	private static function cap() {
		return current_user_can( self::CAP ) ? self::CAP : 'manage_options';
	}

	public static function menu() {
		add_menu_page( 'WMS Attribution', 'WMS Attribution', self::cap(), 'wms-attribution', array( __CLASS__, 'page' ), 'dashicons-chart-area', 56 );
	}

	private static function filters() {
		$f = array();
		foreach ( array( 'type', 'affiliate', 'source', 'q', 'from', 'to' ) as $k ) {
			$f[ $k ] = isset( $_GET[ $k ] ) ? sanitize_text_field( wp_unslash( $_GET[ $k ] ) ) : ''; // phpcs:ignore WordPress.Security.NonceVerification
		}
		return $f;
	}

	public static function page() {
		if ( ! current_user_can( self::cap() ) ) {
			return;
		}
		$tab = isset( $_GET['tab'] ) ? sanitize_key( $_GET['tab'] ) : 'log'; // phpcs:ignore
		$url = admin_url( 'admin.php?page=wms-attribution' );
		echo '<div class="wrap"><h1>WMS Attribution</h1><nav class="nav-tab-wrapper">';
		foreach ( array( 'log' => 'Conversions', 'summary' => 'Summary by affiliate', 'settings' => 'Settings & links' ) as $k => $label ) {
			printf( '<a class="nav-tab %s" href="%s">%s</a>', $tab === $k ? 'nav-tab-active' : '', esc_url( $url . '&tab=' . $k ), esc_html( $label ) );
		}
		echo '</nav>';
		if ( 'summary' === $tab ) {
			self::summary_tab();
		} elseif ( 'settings' === $tab ) {
			self::settings_tab();
		} else {
			self::log_tab();
		}
		echo '</div>';
	}

	/* ---------------------------------------------------------- conversions */

	private static function select( $name, $options, $current, $all ) {
		echo '<select name="' . esc_attr( $name ) . '"><option value="">' . esc_html( $all ) . '</option>';
		foreach ( $options as $v => $label ) {
			printf( '<option value="%s" %s>%s</option>', esc_attr( $v ), selected( $current, (string) $v, false ), esc_html( $label ) );
		}
		echo '</select> ';
	}

	private static function log_tab() {
		$f     = self::filters();
		$paged = isset( $_GET['paged'] ) ? max( 1, (int) $_GET['paged'] ) : 1; // phpcs:ignore
		$per   = 50;
		$rows  = WMS_Attr_Log::query( $f + array( 'limit' => $per, 'offset' => ( $paged - 1 ) * $per ) );
		$total = WMS_Attr_Log::query( $f, true );

		$types = self::TYPE_LABELS;
		$affs  = array_combine( WMS_Attr_Log::distinct( 'affiliate' ), WMS_Attr_Log::distinct( 'affiliate' ) );
		$srcs  = array_combine( WMS_Attr_Log::distinct( 'source' ), WMS_Attr_Log::distinct( 'source' ) );

		echo '<form method="get" style="margin:12px 0"><input type="hidden" name="page" value="wms-attribution">';
		self::select( 'type', $types, $f['type'], 'All actions' );
		self::select( 'affiliate', $affs ? $affs : array(), $f['affiliate'], 'All affiliates' );
		self::select( 'source', $srcs ? $srcs : array(), $f['source'], 'All sources' );
		printf( 'From <input type="date" name="from" value="%s"> to <input type="date" name="to" value="%s"> ', esc_attr( $f['from'] ), esc_attr( $f['to'] ) );
		printf( '<input type="search" name="q" value="%s" placeholder="WMS Ref, phone, email, order #" style="width:220px"> ', esc_attr( $f['q'] ) );
		submit_button( 'Filter', 'secondary', '', false );
		$csv = wp_nonce_url( add_query_arg( array_filter( $f ) + array( 'action' => 'wms_attr_csv' ), admin_url( 'admin-post.php' ) ), 'wms_attr_csv' );
		echo ' <a class="button" href="' . esc_url( $csv ) . '">Export CSV</a></form>';

		if ( '' !== $f['q'] && preg_match( '/^WMS-[A-Z0-9]{6}$/i', $f['q'] ) ) {
			echo '<div class="notice notice-info inline"><p>Showing the full journey of visitor <strong>' . esc_html( strtoupper( $f['q'] ) ) . '</strong> — every action they took, newest first.</p></div>';
		}

		printf( '<p>%d records</p>', (int) $total );
		echo '<table class="widefat striped"><thead><tr><th>Date</th><th>Action</th><th>Affiliate</th><th>Source / Medium</th><th>Campaign</th><th>Contact</th><th>Amount</th><th>Route (how they got here)</th><th>WMS Ref</th></tr></thead><tbody>';
		if ( ! $rows ) {
			echo '<tr><td colspan="9">No conversions yet.</td></tr>';
		}
		foreach ( (array) $rows as $r ) {
			$ref_link = $r['visitor_ref'] ? '<a href="' . esc_url( admin_url( 'admin.php?page=wms-attribution&q=' . rawurlencode( $r['visitor_ref'] ) ) ) . '">' . esc_html( $r['visitor_ref'] ) . '</a>' : '';
			$action   = '<strong>' . esc_html( isset( $types[ $r['type'] ] ) ? $types[ $r['type'] ] : $r['type'] ) . '</strong><br>' . esc_html( $r['label'] );
			if ( $r['order_id'] ) {
				$action = '<strong>Purchase</strong><br><a href="' . esc_url( self::order_url( (int) $r['order_id'] ) ) . '">' . esc_html( $r['label'] ) . '</a>';
			}
			$where    = trim( $r['page'] . ( $r['location'] ? ' · ' . $r['location'] : '' ) );
			$contact  = implode( '<br>', array_map( 'esc_html', array_filter( array( $r['contact_name'], $r['contact_phone'], $r['contact_email'] ) ) ) );
			printf(
				'<tr><td>%s</td><td>%s<br><small style="color:#777">%s</small></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><small>%s%s</small></td><td>%s</td></tr>',
				esc_html( get_date_from_gmt( $r['created_at'], 'd M Y H:i' ) ),
				$action, // phpcs:ignore WordPress.Security.EscapeOutput -- escaped above
				esc_html( $where ),
				esc_html( $r['affiliate'] ? $r['affiliate'] : '—' ),
				esc_html( $r['source'] . ( $r['medium'] ? ' / ' . $r['medium'] : '' ) ),
				esc_html( $r['campaign'] ),
				$contact, // phpcs:ignore WordPress.Security.EscapeOutput
				null !== $r['amount'] ? esc_html( 'RM' . number_format_i18n( (float) $r['amount'], 2 ) ) : '',
				esc_html( (string) $r['route'] ),
				$r['first_touch'] ? '<br><em>First touch: ' . esc_html( $r['first_touch'] ) . '</em>' : '',
				$ref_link // phpcs:ignore WordPress.Security.EscapeOutput
			);
		}
		echo '</tbody></table>';

		$pages = (int) ceil( $total / $per );
		if ( $pages > 1 ) {
			echo '<p>';
			for ( $i = 1; $i <= min( $pages, 50 ); $i++ ) {
				$link = add_query_arg( array_filter( $f ) + array( 'page' => 'wms-attribution', 'paged' => $i ), admin_url( 'admin.php' ) );
				printf( $i === $paged ? '<strong>%2$d</strong> ' : '<a href="%1$s">%2$d</a> ', esc_url( $link ), (int) $i );
			}
			echo '</p>';
		}
	}

	private static function order_url( $id ) {
		$order = function_exists( 'wc_get_order' ) ? wc_get_order( $id ) : null;
		return $order ? $order->get_edit_order_url() : admin_url( 'post.php?post=' . $id . '&action=edit' );
	}

	public static function csv() {
		if ( ! current_user_can( self::cap() ) || ! check_admin_referer( 'wms_attr_csv' ) ) {
			wp_die( 'Not allowed' );
		}
		$rows = WMS_Attr_Log::query( self::filters() + array( 'limit' => 50000 ) );
		nocache_headers();
		header( 'Content-Type: text/csv; charset=utf-8' );
		header( 'Content-Disposition: attachment; filename=wms-conversions-' . gmdate( 'Ymd' ) . '.csv' );
		$out = fopen( 'php://output', 'w' );
		fwrite( $out, "\xEF\xBB\xBF" ); // Excel UTF-8
		$cols = array( 'id', 'created_at', 'type', 'label', 'location', 'page', 'affiliate', 'source', 'medium', 'campaign', 'content', 'term', 'landing_page', 'referrer', 'first_touch', 'visitor_ref', 'route', 'contact_name', 'contact_email', 'contact_phone', 'amount', 'order_id' );
		fputcsv( $out, $cols );
		foreach ( (array) $rows as $r ) {
			$line = array();
			foreach ( $cols as $c ) {
				$v = (string) $r[ $c ];
				$line[] = preg_match( '/^[=+\-@]/', $v ) ? "'" . $v : $v; // no spreadsheet formulas
			}
			fputcsv( $out, $line );
		}
		fclose( $out );
		exit;
	}

	/* -------------------------------------------------------------- summary */

	private static function summary_tab() {
		$f    = self::filters();
		$from = $f['from'] ? $f['from'] : wp_date( 'Y-m-d', strtotime( '-30 days' ) );
		$to   = $f['to'] ? $f['to'] : wp_date( 'Y-m-d' );
		echo '<form method="get" style="margin:12px 0"><input type="hidden" name="page" value="wms-attribution"><input type="hidden" name="tab" value="summary">';
		printf( 'From <input type="date" name="from" value="%s"> to <input type="date" name="to" value="%s"> ', esc_attr( $from ), esc_attr( $to ) );
		submit_button( 'Show', 'secondary', '', false );
		echo '</form>';

		$types = array( 'purchase', 'form_submit', 'ghl_form', 'whatsapp', 'call', 'cta_click', 'add_to_cart' );
		$grid  = array();
		foreach ( WMS_Attr_Log::summary( $from, $to ) as $r ) {
			$k = $r['affiliate'] . '||' . $r['source'];
			if ( ! isset( $grid[ $k ] ) ) {
				$grid[ $k ] = array( 'revenue' => 0 );
			}
			$grid[ $k ][ $r['type'] ] = (int) $r['n'];
			$grid[ $k ]['revenue']   += (float) $r['revenue'];
		}
		echo '<table class="widefat striped"><thead><tr><th>Affiliate</th><th>Source</th>';
		foreach ( $types as $t ) {
			echo '<th>' . esc_html( self::TYPE_LABELS[ $t ] ) . '</th>';
		}
		echo '<th>Revenue</th></tr></thead><tbody>';
		if ( ! $grid ) {
			echo '<tr><td colspan="' . ( count( $types ) + 3 ) . '">No data in this period.</td></tr>';
		}
		foreach ( $grid as $k => $row ) {
			list( $aff, $src ) = explode( '||', $k );
			$link = admin_url( 'admin.php?page=wms-attribution&from=' . $from . '&to=' . $to . '&source=' . rawurlencode( $src ) . ( '(no affiliate)' !== $aff ? '&affiliate=' . rawurlencode( $aff ) : '' ) );
			echo '<tr><td><a href="' . esc_url( $link ) . '"><strong>' . esc_html( $aff ) . '</strong></a></td><td>' . esc_html( $src ) . '</td>';
			foreach ( $types as $t ) {
				echo '<td>' . ( isset( $row[ $t ] ) ? (int) $row[ $t ] : '' ) . '</td>';
			}
			echo '<td>' . ( $row['revenue'] ? esc_html( 'RM' . number_format_i18n( $row['revenue'], 2 ) ) : '' ) . '</td></tr>';
		}
		echo '</tbody></table>';
	}

	/* ------------------------------------------------------------- settings */

	private static function settings_tab() {
		$s = WMS_Attr_Core::settings();
		if ( isset( $_GET['saved'] ) ) { // phpcs:ignore
			echo '<div class="notice notice-success"><p>Saved.</p></div>';
		}
		$home = home_url( '/' );
		echo '<form method="post" action="' . esc_url( admin_url( 'admin-post.php' ) ) . '">';
		wp_nonce_field( 'wms_attr_save' );
		echo '<input type="hidden" name="action" value="wms_attr_save"><table class="form-table">';
		echo '<tr><th>Affiliate links</th><td><textarea name="affiliates" rows="10" cols="50" class="code">' . esc_textarea( $s['affiliates'] ) . '</textarea>';
		echo '<p class="description">One per line: <code>slug | Display name</code>. <code>' . esc_html( $home ) . 'might</code> and <code>' . esc_html( $home ) . '?ref=might</code> both credit the affiliate. Unknown <code>?ref=</code> codes are still recorded (in capitals).</p></td></tr>';
		printf( '<tr><th>Remember visitor for</th><td><input type="number" name="days" min="1" max="365" value="%d"> days</td></tr>', (int) $s['days'] );
		printf( '<tr><th>WhatsApp reference</th><td><label><input type="checkbox" name="wa_ref" value="1" %s> Add <code>[Ref WMS-XXXXXX · Affiliate · source/campaign]</code> to WhatsApp messages</label></td></tr>', checked( $s['wa_ref'], 1, false ) );
		printf( '<tr><th>Extra GHL / funnel domains</th><td><input type="text" name="ghl_hosts" class="regular-text" value="%s" placeholder="e.g. daftar.wmsmalaysia.com"><p class="description">LeadConnector / msgsndr domains are included automatically. Add any GHL custom domain here so its forms and links receive the attribution.</p></td></tr>', esc_attr( $s['ghl_hosts'] ) );
		printf( '<tr><th>Cookie domain</th><td><input type="text" name="cookie_domain" class="regular-text" value="%s" placeholder=".wmsmalaysia.com"><p class="description">Optional. Set to <code>.wmsmalaysia.com</code> to share tracking with sub-domains.</p></td></tr>', esc_attr( $s['cookie_domain'] ) );
		echo '</table>';
		submit_button( 'Save settings' );
		echo '</form>';

		echo '<h2>Ready-to-use affiliate links</h2><table class="widefat striped" style="max-width:900px"><thead><tr><th>Affiliate</th><th>Plain link</th><th>Example with UTM (Facebook ads)</th></tr></thead><tbody>';
		foreach ( WMS_Attr_Core::affiliates() as $slug => $name ) {
			$plain = $home . $slug;
			$utm   = $plain . '?utm_source=facebook&utm_medium=paid_social&utm_campaign=' . $slug . '_ads';
			printf( '<tr><td>%s</td><td><code>%s</code></td><td><code>%s</code></td></tr>', esc_html( $name ), esc_html( $plain ), esc_html( $utm ) );
		}
		echo '</tbody></table>';
		echo '<p class="description">If an affiliate slug is a <em>redirect</em> (e.g. in the Redirection plugin), it still works. For extra safety with page caching or a CDN, add <code>?ref=slug</code> to the redirect target, e.g. <code>/might → /?ref=might</code>.</p>';
	}

	public static function save_settings() {
		if ( ! current_user_can( self::cap() ) || ! check_admin_referer( 'wms_attr_save' ) ) {
			wp_die( 'Not allowed' );
		}
		$in = wp_unslash( $_POST ); // phpcs:ignore WordPress.Security.ValidatedSanitizedInput
		update_option(
			WMS_Attr_Core::OPTION,
			array(
				'affiliates'    => sanitize_textarea_field( isset( $in['affiliates'] ) ? $in['affiliates'] : '' ),
				'days'          => min( 365, max( 1, (int) ( isset( $in['days'] ) ? $in['days'] : 90 ) ) ),
				'wa_ref'        => empty( $in['wa_ref'] ) ? 0 : 1,
				'ghl_hosts'     => sanitize_text_field( isset( $in['ghl_hosts'] ) ? $in['ghl_hosts'] : '' ),
				'cookie_domain' => sanitize_text_field( isset( $in['cookie_domain'] ) ? $in['cookie_domain'] : '' ),
			)
		);
		wp_safe_redirect( admin_url( 'admin.php?page=wms-attribution&tab=settings&saved=1' ) );
		exit;
	}
}
