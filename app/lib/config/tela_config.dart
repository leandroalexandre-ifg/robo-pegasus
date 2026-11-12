import 'package:flutter/material.dart';

import 'config.dart';

/// Diálogo para trocar o endereço do servidor, o token e o id do tablet.
/// Abre com um toque longo no rosto; não há botão visível.
Future<Config?> editarConfig(BuildContext context, Config atual) {
  return showDialog<Config>(
    context: context,
    builder: (context) => _DialogoConfig(atual: atual),
  );
}

class _DialogoConfig extends StatefulWidget {
  const _DialogoConfig({required this.atual});
  final Config atual;

  @override
  State<_DialogoConfig> createState() => _DialogoConfigState();
}

class _DialogoConfigState extends State<_DialogoConfig> {
  final _form = GlobalKey<FormState>();
  late final _url = TextEditingController(text: widget.atual.url);
  late final _token = TextEditingController(text: widget.atual.token);
  late final _device = TextEditingController(text: widget.atual.deviceId);

  @override
  void dispose() {
    _url.dispose();
    _token.dispose();
    _device.dispose();
    super.dispose();
  }

  void _salvar() {
    if (!_form.currentState!.validate()) return;
    Navigator.of(context).pop(
      Config(
        url: _url.text.trim(),
        token: _token.text.trim(),
        deviceId: _device.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Servidor'),
      content: Form(
        key: _form,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _url,
                decoration: const InputDecoration(
                  labelText: 'Endereço',
                  hintText: 'ws://192.168.0.10:8000/ws',
                ),
                keyboardType: TextInputType.url,
                autocorrect: false,
                validator: (v) => Config.validarUrl(v ?? ''),
              ),
              TextFormField(
                controller: _token,
                decoration: const InputDecoration(labelText: 'Token'),
                obscureText: true,
                autocorrect: false,
              ),
              TextFormField(
                controller: _device,
                decoration: const InputDecoration(
                  labelText: 'Identificação do tablet',
                ),
                autocorrect: false,
                validator: (v) =>
                    (v ?? '').trim().isEmpty ? 'Dê um nome ao tablet' : null,
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(onPressed: _salvar, child: const Text('Salvar')),
      ],
    );
  }
}
