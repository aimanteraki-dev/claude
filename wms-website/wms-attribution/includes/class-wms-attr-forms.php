<?php
/**
 * Server-side capture of form submissions from the common WordPress form plugins.
 *
 * The browser script already puts hidden attribution fields into every form. Here we also:
 *  - log each submission (with name / email / phone) in the WMS conversions table, and
 *  - add attribution to the form's own record, so admin emails and webhooks (e.g. to GHL) carry it.
 */

defined( 'ABSPATH' ) || exit;

class WMS_Attr_Forms {

	/** Labels used when attribution is added to form records and emails. */
	const LABELS = array(
		'affiliate'    => 'Affiliate',
		'utm_source'   => 'Source',
		'utm_medium'   => 'Medium',
		'utm_campaign' => 'Campaign',
		'utm_content'  => 'Content',
		'landing_page' => 'Landing page',
		'wms_ref'      => 'WMS Ref',
		'wms_route'    => 'Route',
	);

	public static function init() {
		// Elementor Pro forms.
		add_action( 'elementor_pro/forms/process', array( __CLASS__, 'elementor_enrich' ), 1, 2 );
		add_action( 'elementor_pro/forms/new_record', array( __CLASS__, 'elementor_log' ), 10, 2 );
		// Contact Form 7.
		add_action( 'wpcf7_before_send_mail', array( __CLASS__, 'cf7_log' ), 10, 1 );
		add_filter( 'wpcf7_mail_components', array( __CLASS__, 'cf7_mail' ), 10, 1 );
		// WPForms.
		add_action( 'wpforms_process_complete', array( __CLASS__, 'wpforms_log' ), 10, 4 );
		// Fluent Forms (new and legacy hook names).
		add_action( 'fluentform/submission_inserted', array( __CLASS__, 'fluent_log' ), 10, 3 );
		add_action( 'fluentform_submission_inserted', array( __CLASS__, 'fluent_log' ), 10, 3 );
		// Gravity Forms.
		add_action( 'gform_after_submission', array( __CLASS__, 'gravity_log' ), 10, 2 );
	}

	/** Pull name / email / phone / company out of any key => value field list. */
	public static function contact_from( array $fields ) {
		$out = array();
		foreach ( $fields as $key => $value ) {
			if ( is_array( $value ) && isset( $value['type'] ) && 'hidden' === $value['type'] ) {
				continue;
			}
			if ( is_array( $value ) ) {
				// Plugin field objects: [ 'id'/'name'/'label' => ..., 'value' => ..., 'type' => ... ].
				$v   = isset( $value['value'] ) && is_scalar( $value['value'] ) ? (string) $value['value'] : '';
				$key = strtolower( implode( ' ', array_filter( array( (string) $key, isset( $value['id'] ) ? $value['id'] : '', isset( $value['name'] ) ? $value['name'] : '', isset( $value['title'] ) ? $value['title'] : '', isset( $value['label'] ) ? $value['label'] : '', isset( $value['type'] ) ? $value['type'] : '' ), 'is_scalar' ) ) );
			} else {
				$v   = is_scalar( $value ) ? (string) $value : '';
				$key = strtolower( (string) $key );
			}
			$v = trim( $v );
			if ( '' === $v || isset( self::LABELS[ trim( $key ) ] ) ) {
				continue;
			}
			if ( empty( $out['email'] ) && ( is_email( $v ) || false !== strpos( $key, 'mail' ) ) ) {
				$out['email'] = $v;
			} elseif ( empty( $out['phone'] ) && preg_match( '/phone|tel|mobile|whatsapp|\bhp\b|telefon/', $key ) ) {
				$out['phone'] = $v;
			} elseif ( empty( $out['company'] ) && preg_match( '/company|syarikat|organi[sz]ation|organisasi/', $key ) ) {
				$out['company'] = $v;
			} elseif ( empty( $out['name'] ) && preg_match( '/name|nama/', $key ) ) {
				$out['name'] = $v;
			}
		}
		return $out;
	}

	/** Attribution for a server-side form submission: cookie first, posted hidden fields as fallback. */
	private static function attr( array $posted = array() ) {
		$flat = array();
		foreach ( $posted as $k => $v ) {
			if ( is_array( $v ) && isset( $v['value'] ) ) {
				$v = $v['value'];
			}
			if ( is_scalar( $v ) ) {
				$flat[ preg_replace( '/^.*\[([^\]]+)\]$/', '$1', (string) $k ) ] = $v;
			}
		}
		return WMS_Attr_Core::current( $flat );
	}

	private static function page() {
		$ref = isset( $_SERVER['HTTP_REFERER'] ) ? (string) wp_parse_url( wp_unslash( $_SERVER['HTTP_REFERER'] ), PHP_URL_PATH ) : ''; // phpcs:ignore
		return $ref;
	}

	private static function log( $label, array $fields ) {
		WMS_Attr_Log::add(
			'form_submit',
			self::attr( $fields ),
			array(
				'label'   => $label,
				'page'    => self::page(),
				'contact' => self::contact_from( $fields ),
			)
		);
	}

	/* ------------------------------------------------------------ Elementor */

	/** Put attribution into the Elementor record so emails ([all-fields]) and webhooks to GHL include it. */
	public static function elementor_enrich( $record, $handler = null ) {
		if ( ! is_object( $record ) || ! method_exists( $record, 'get' ) ) {
			return;
		}
		$fields = $record->get( 'fields' );
		if ( ! is_array( $fields ) ) {
			return;
		}
		$attr = self::attr( $fields );
		foreach ( self::LABELS as $key => $title ) {
			$value = (string) $attr[ $key ];
			if ( isset( $fields[ $key ] ) ) {
				$fields[ $key ]['value']     = $value;   // a hidden field with this ID already exists
				$fields[ $key ]['raw_value'] = $value;
			} else {
				$fields[ $key ] = array(
					'id'        => $key,
					'type'      => 'hidden',
					'title'     => $title,
					'value'     => $value,
					'raw_value' => $value,
					'required'  => false,
				);
			}
		}
		if ( method_exists( $record, 'set' ) ) {
			$record->set( 'fields', $fields );
		}
	}

	public static function elementor_log( $record, $handler = null ) {
		if ( ! is_object( $record ) || ! method_exists( $record, 'get' ) ) {
			return;
		}
		$fields = (array) $record->get( 'fields' );
		$name   = method_exists( $record, 'get_form_settings' ) ? (string) $record->get_form_settings( 'form_name' ) : '';
		self::log( '' !== $name ? $name : 'Elementor form', $fields );
	}

	/* ----------------------------------------------------------------- CF7 */

	public static function cf7_log( $form ) {
		if ( ! class_exists( 'WPCF7_Submission' ) ) {
			return;
		}
		$sub = WPCF7_Submission::get_instance();
		$data = $sub ? (array) $sub->get_posted_data() : array();
		self::log( is_object( $form ) && method_exists( $form, 'title' ) ? $form->title() : 'Contact Form 7', $data );
	}

	public static function cf7_mail( $components ) {
		if ( isset( $components['body'] ) && is_string( $components['body'] ) && false === strpos( $components['body'], 'WMS Ref:' ) ) {
			$attr   = self::attr( class_exists( 'WPCF7_Submission' ) && WPCF7_Submission::get_instance() ? (array) WPCF7_Submission::get_instance()->get_posted_data() : array() );
			$html   = false !== stripos( $components['body'], '<br' ) || false !== stripos( $components['body'], '</p>' );
			$lines  = array();
			foreach ( self::LABELS as $key => $title ) {
				if ( '' !== (string) $attr[ $key ] ) {
					$lines[] = $title . ': ' . ( $html ? esc_html( $attr[ $key ] ) : $attr[ $key ] );
				}
			}
			$components['body'] .= $html ? '<br><br>--<br>' . implode( '<br>', $lines ) : "\n\n--\n" . implode( "\n", $lines );
		}
		return $components;
	}

	/* ---------------------------------------------------- WPForms / Fluent / Gravity */

	public static function wpforms_log( $fields, $entry, $form_data, $entry_id = 0 ) {
		$posted = is_array( $fields ) ? $fields : array();
		// Hidden inputs added by the browser script arrive outside WPForms' own field list.
		foreach ( array_keys( self::LABELS ) as $k ) {
			if ( isset( $_POST[ $k ] ) && is_string( $_POST[ $k ] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
				$posted[ $k ] = sanitize_text_field( wp_unslash( $_POST[ $k ] ) ); // phpcs:ignore
			}
		}
		$title = isset( $form_data['settings']['form_title'] ) ? $form_data['settings']['form_title'] : 'WPForms';
		self::log( $title, $posted );
	}

	public static function fluent_log( $entry_id, $form_data, $form = null ) {
		$title = is_object( $form ) && isset( $form->title ) ? $form->title : 'Fluent Form';
		self::log( $title, is_array( $form_data ) ? $form_data : array() );
	}

	public static function gravity_log( $entry, $form ) {
		$fields = array();
		if ( is_array( $form ) && ! empty( $form['fields'] ) ) {
			foreach ( $form['fields'] as $f ) {
				$id    = is_object( $f ) ? $f->id : ( isset( $f['id'] ) ? $f['id'] : '' );
				$label = is_object( $f ) ? $f->label : ( isset( $f['label'] ) ? $f['label'] : '' );
				$type  = is_object( $f ) ? $f->type : ( isset( $f['type'] ) ? $f['type'] : '' );
				if ( isset( $entry[ $id ] ) ) {
					$fields[ $label . ' ' . $type ] = $entry[ $id ];
				}
			}
		}
		foreach ( array_keys( self::LABELS ) as $k ) {
			if ( isset( $_POST[ $k ] ) && is_string( $_POST[ $k ] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
				$fields[ $k ] = sanitize_text_field( wp_unslash( $_POST[ $k ] ) ); // phpcs:ignore
			}
		}
		self::log( isset( $form['title'] ) ? $form['title'] : 'Gravity Form', $fields );
	}
}
